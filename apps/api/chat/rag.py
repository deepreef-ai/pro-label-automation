"""Small local RAG index over the company's documents.

Corpus: ``core.etl.docs.list_documents("data/raw")`` when ``data/raw`` exists (real client
documents, git-ignored), otherwise the committed ``docs/*.md`` plus ``contract/SPEC.md``.
Texts are cut into ~900-character chunks.

Search:
* **semantic**: fastembed ``BAAI/bge-small-en-v1.5`` on CPU, cosine similarity with numpy.
  Used only when the model is already on disk (``data/rag/models``) or ``CHAT_RAG_DOWNLOAD=1``,
  and never under pytest, so tests/CI never download a model. Build once with
  ``PYTHONPATH=apps/api python -m chat.rag --build``.
* **keyword** (BM25) otherwise, or if anything in the semantic path fails.

The chunk list and vectors are cached under the git-ignored ``data/rag/``.

Per company (SPEC 6.4): the demo company ``CO-001`` keeps the corpus and cache above. Any other
company reads only its own folder ``data/rag/<company_id>/`` (documents in it or in its ``docs/``
subfolder; cache files next to them). An empty or missing folder means no hits, so the chat
falls back to its deterministic how-to answer. Each company has its own in-memory cache, and a
search never looks at another company's documents. Only the embedding model is shared.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import os
import re
import threading
from collections import Counter
from pathlib import Path

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[3]
RAW_DIR = ROOT / "data" / "raw"
CACHE_DIR = ROOT / "data" / "rag"
MODEL_DIR = CACHE_DIR / "models"
MODEL_NAME = "BAAI/bge-small-en-v1.5"
CHUNK = 900
OVERLAP = 150

DEMO_COMPANY = "CO-001"  # keeps the original corpus and cache location
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")

_lock = threading.Lock()
_model_state: dict = {"model": None}
_states: dict[str, dict] = {}


def _company_key(company_id: str | None) -> str:
    if company_id:
        return str(company_id)
    from core.tenancy import default_company

    return default_company()


def _state_for(company_id: str | None) -> dict:
    """The per-company index state (corpus paths, chunks, BM25, vectors, last method)."""
    key = _company_key(company_id)
    st = _states.get(key)
    if st is None:
        if key == DEMO_COMPANY:
            st = {"raw": RAW_DIR, "cache": CACHE_DIR, "docs": None}
        elif _SAFE_ID.match(key) and key.lower() != MODEL_DIR.name:
            folder = CACHE_DIR / key
            st = {"raw": None, "cache": folder, "docs": folder}
        else:  # never build a path from an odd id
            st = {"raw": None, "cache": None, "docs": None}
        st.update(company=key, chunks=None, sig=None, bm25=None, vectors=None, method="none")
        _states[key] = st
    return st


# ----------------------------------------------------------------- corpus

def _doc_files(base: Path) -> list[Path]:
    folder = base / "docs" if (base / "docs").is_dir() else base
    return sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in (".pdf", ".txt", ".md"))


def _sources(st: dict) -> list[Path]:
    if st["docs"] is not None:  # another company: only its own folder
        return _doc_files(st["docs"]) if st["docs"].is_dir() else []
    if st["raw"] is None:
        return []
    if st["raw"].is_dir():
        return _doc_files(st["raw"])
    files = sorted((ROOT / "docs").glob("*.md")) if (ROOT / "docs").is_dir() else []
    spec = ROOT / "contract" / "SPEC.md"
    return files + ([spec] if spec.exists() else [])


def _signature(paths: list[Path]) -> str:
    h = hashlib.sha256()
    for p in paths:
        st = p.stat()
        h.update(f"{p.name}|{st.st_size}|{int(st.st_mtime)}".encode())
    return h.hexdigest()[:16]


def _split(text: str) -> list[str]:
    text = text.strip()
    if len(text) <= CHUNK:
        return [text] if text else []
    out, start = [], 0
    while start < len(text):
        end = min(len(text), start + CHUNK)
        if end < len(text):  # prefer to cut at a sentence/line break
            cut = max(text.rfind("\n", start + CHUNK // 2, end), text.rfind(". ", start + CHUNK // 2, end))
            if cut > start:
                end = cut + 1
        out.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - OVERLAP, start + 1)
    return [c for c in out if len(c) >= 20]


def _load_documents(st: dict, paths: list[Path]) -> list[dict]:
    base = st["docs"] if st["docs"] is not None else st["raw"]
    if base is not None and base.is_dir():
        from core.etl.docs import list_documents

        return list_documents(base)
    docs = []
    for p in paths:
        text = p.read_text(encoding="utf-8", errors="replace")
        for i, block in enumerate(re.split(r"\n(?=#{1,3} )", text), start=1):
            if block.strip():
                docs.append({"source": p.name, "page": i, "text": block})
    return docs


def _chunks(st: dict) -> list[dict]:
    paths = _sources(st)
    sig = _signature(paths) if paths else "empty"
    if st["chunks"] is not None and st["sig"] == sig:
        return st["chunks"]
    if not paths:  # nothing to index (e.g. a company without documents yet)
        st.update(chunks=[], sig=sig, bm25=None, vectors=None)
        return []
    cache = st["cache"] / "chunks.json"
    chunks = None
    try:
        if cache.exists():
            data = json.loads(cache.read_text(encoding="utf-8"))
            if data.get("sig") == sig:
                chunks = data["chunks"]
    except (OSError, ValueError, KeyError):
        chunks = None
    if chunks is None:
        chunks = []
        for d in _load_documents(st, paths):
            for piece in _split(d["text"]):
                chunks.append({"source": d["source"], "page": d.get("page"), "text": piece})
        try:
            st["cache"].mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps({"sig": sig, "chunks": chunks}, ensure_ascii=False), encoding="utf-8")
        except OSError as exc:
            log.debug("rag: cannot write chunk cache: %s", exc)
    st.update(chunks=chunks, sig=sig, bm25=None, vectors=None)
    return chunks


# ----------------------------------------------------------------- keyword (BM25)

_TOKEN = re.compile(r"[a-z0-9ऀ-ॿ]+")
_STOP = set("a an the of to in on for and or is are was be how do i we you it this that with what "
            "which can my our me from by at as".split())


def _tokens(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOP and len(t) > 1]


class BM25:
    def __init__(self, docs: list[str], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.tfs = [Counter(_tokens(d)) for d in docs]
        self.lens = [sum(tf.values()) for tf in self.tfs]
        self.avg = (sum(self.lens) / len(self.lens)) if self.lens else 0.0
        df: Counter = Counter()
        for tf in self.tfs:
            df.update(tf.keys())
        n = len(docs)
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}

    def scores(self, query: str) -> list[float]:
        q = _tokens(query)
        out = []
        for tf, length in zip(self.tfs, self.lens, strict=False):
            s = 0.0
            for t in q:
                f = tf.get(t)
                if f:
                    s += self.idf[t] * f * (self.k1 + 1) / (
                        f + self.k1 * (1 - self.b + self.b * length / (self.avg or 1)))
            out.append(s)
        return out


# ----------------------------------------------------------------- semantic (fastembed)

def _semantic_allowed() -> bool:
    if os.getenv("PYTEST_CURRENT_TEST") or os.getenv("CHAT_RAG_MODE", "").lower() == "keyword":
        return False
    if os.getenv("CHAT_RAG_DOWNLOAD", "").strip() in ("1", "true", "yes"):
        return True
    return MODEL_DIR.is_dir() and any(MODEL_DIR.iterdir())


def _model():
    if _model_state["model"] is None:
        from fastembed import TextEmbedding

        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        _model_state["model"] = TextEmbedding(model_name=MODEL_NAME, cache_dir=str(MODEL_DIR))
    return _model_state["model"]


def _vectors(st: dict, chunks: list[dict]):
    import numpy as np

    if st["vectors"] is not None:
        return st["vectors"]
    path = st["cache"] / f"vectors_{st['sig']}.npy"
    if path.exists():
        vecs = np.load(path)
        if len(vecs) == len(chunks):
            st["vectors"] = vecs
            return vecs
    vecs = np.array(list(_model().embed([c["text"] for c in chunks])), dtype="float32")
    vecs /= np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-9
    try:
        st["cache"].mkdir(parents=True, exist_ok=True)
        np.save(path, vecs)
    except OSError as exc:
        log.debug("rag: cannot write vectors: %s", exc)
    st["vectors"] = vecs
    return vecs


def _semantic(st: dict, query: str, chunks: list[dict], k: int) -> list[tuple[int, float]]:
    import numpy as np

    vecs = _vectors(st, chunks)
    q = np.array(next(iter(_model().query_embed([query]))), dtype="float32")
    q /= np.linalg.norm(q) + 1e-9
    sims = vecs @ q
    order = np.argsort(-sims)[:k]
    return [(int(i), float(sims[i])) for i in order]


# ----------------------------------------------------------------- public

def search(query: str, k: int = 4, company_id: str | None = None) -> list[dict]:
    """Top-k chunks of ``company_id``'s documents only (None = the default company):
    ``[{"source", "page", "text", "score"}]`` (text trimmed to ~600 chars)."""
    with _lock:
        st = _state_for(company_id)
        try:
            chunks = _chunks(st)
        except Exception as exc:
            log.warning("rag: could not load documents: %s", exc)
            st["method"] = "none"
            return []
        if not chunks or not query.strip():
            return []
        ranked: list[tuple[int, float]] | None = None
        if _semantic_allowed():
            try:
                ranked = _semantic(st, query, chunks, k)
                st["method"] = "semantic"
            except Exception as exc:
                log.warning("rag: semantic search unavailable (%s); using keyword search", exc)
                ranked = None
        if ranked is None:
            if st["bm25"] is None:
                st["bm25"] = BM25([c["text"] for c in chunks])
            scores = st["bm25"].scores(query)
            order = sorted(range(len(scores)), key=lambda i: -scores[i])[:k]
            ranked = [(i, scores[i]) for i in order if scores[i] > 0]
            st["method"] = "keyword"
    return [{"source": chunks[i]["source"], "page": chunks[i].get("page"),
             "text": chunks[i]["text"][:600], "score": round(s, 4)} for i, s in ranked]


def last_method(company_id: str | None = None) -> str:
    return _state_for(company_id)["method"]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build / query the chat RAG index")
    ap.add_argument("--build", action="store_true", help="download the model and embed all chunks")
    ap.add_argument("--company", default=None, help="company id (default: the demo company)")
    ap.add_argument("query", nargs="?", default="")
    a = ap.parse_args(argv)
    if a.build:
        os.environ["CHAT_RAG_DOWNLOAD"] = "1"
        st = _state_for(a.company)
        chunks = _chunks(st)
        if chunks:
            _vectors(st, chunks)
        print(f"indexed {len(chunks)} chunks into {st['cache']}")
    if a.query:
        for h in search(a.query, company_id=a.company):
            print(f"[{h['score']}] {h['source']} p.{h['page']}: {h['text'][:160]!r}")
        print("method:", last_method(a.company))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
