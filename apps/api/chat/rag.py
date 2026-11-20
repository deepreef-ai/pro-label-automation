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

_lock = threading.Lock()
_state: dict = {"chunks": None, "sig": None, "bm25": None, "vectors": None, "model": None,
                "method": "none"}


# ----------------------------------------------------------------- corpus

def _sources() -> list[Path]:
    if RAW_DIR.is_dir():
        folder = RAW_DIR / "docs" if (RAW_DIR / "docs").is_dir() else RAW_DIR
        return sorted(p for p in folder.iterdir() if p.suffix.lower() in (".pdf", ".txt", ".md"))
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


def _load_documents(paths: list[Path]) -> list[dict]:
    if RAW_DIR.is_dir():
        from core.etl.docs import list_documents

        return list_documents(RAW_DIR)
    docs = []
    for p in paths:
        text = p.read_text(encoding="utf-8", errors="replace")
        for i, block in enumerate(re.split(r"\n(?=#{1,3} )", text), start=1):
            if block.strip():
                docs.append({"source": p.name, "page": i, "text": block})
    return docs


def _chunks() -> list[dict]:
    paths = _sources()
    sig = _signature(paths) if paths else "empty"
    if _state["chunks"] is not None and _state["sig"] == sig:
        return _state["chunks"]
    cache = CACHE_DIR / "chunks.json"
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
        for d in _load_documents(paths):
            for piece in _split(d["text"]):
                chunks.append({"source": d["source"], "page": d.get("page"), "text": piece})
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps({"sig": sig, "chunks": chunks}, ensure_ascii=False), encoding="utf-8")
        except OSError as exc:
            log.debug("rag: cannot write chunk cache: %s", exc)
    _state.update(chunks=chunks, sig=sig, bm25=None, vectors=None)
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
    if _state["model"] is None:
        from fastembed import TextEmbedding

        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        _state["model"] = TextEmbedding(model_name=MODEL_NAME, cache_dir=str(MODEL_DIR))
    return _state["model"]


def _vectors(chunks: list[dict]):
    import numpy as np

    if _state["vectors"] is not None:
        return _state["vectors"]
    path = CACHE_DIR / f"vectors_{_state['sig']}.npy"
    if path.exists():
        vecs = np.load(path)
        if len(vecs) == len(chunks):
            _state["vectors"] = vecs
            return vecs
    vecs = np.array(list(_model().embed([c["text"] for c in chunks])), dtype="float32")
    vecs /= np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-9
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        np.save(path, vecs)
    except OSError as exc:
        log.debug("rag: cannot write vectors: %s", exc)
    _state["vectors"] = vecs
    return vecs


def _semantic(query: str, chunks: list[dict], k: int) -> list[tuple[int, float]]:
    import numpy as np

    vecs = _vectors(chunks)
    q = np.array(next(iter(_model().query_embed([query]))), dtype="float32")
    q /= np.linalg.norm(q) + 1e-9
    sims = vecs @ q
    order = np.argsort(-sims)[:k]
    return [(int(i), float(sims[i])) for i in order]


# ----------------------------------------------------------------- public

def search(query: str, k: int = 4) -> list[dict]:
    """Top-k chunks: ``[{"source", "page", "text", "score"}]`` (text trimmed to ~600 chars)."""
    with _lock:
        try:
            chunks = _chunks()
        except Exception as exc:
            log.warning("rag: could not load documents: %s", exc)
            _state["method"] = "none"
            return []
        if not chunks or not query.strip():
            return []
        ranked: list[tuple[int, float]] | None = None
        if _semantic_allowed():
            try:
                ranked = _semantic(query, chunks, k)
                _state["method"] = "semantic"
            except Exception as exc:
                log.warning("rag: semantic search unavailable (%s); using keyword search", exc)
                ranked = None
        if ranked is None:
            if _state["bm25"] is None:
                _state["bm25"] = BM25([c["text"] for c in chunks])
            scores = _state["bm25"].scores(query)
            order = sorted(range(len(scores)), key=lambda i: -scores[i])[:k]
            ranked = [(i, scores[i]) for i in order if scores[i] > 0]
            _state["method"] = "keyword"
    return [{"source": chunks[i]["source"], "page": chunks[i].get("page"),
             "text": chunks[i]["text"][:600], "score": round(s, 4)} for i, s in ranked]


def last_method() -> str:
    return _state["method"]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build / query the chat RAG index")
    ap.add_argument("--build", action="store_true", help="download the model and embed all chunks")
    ap.add_argument("query", nargs="?", default="")
    a = ap.parse_args(argv)
    if a.build:
        os.environ["CHAT_RAG_DOWNLOAD"] = "1"
        chunks = _chunks()
        _vectors(chunks)
        print(f"indexed {len(chunks)} chunks into {CACHE_DIR}")
    if a.query:
        for h in search(a.query):
            print(f"[{h['score']}] {h['source']} p.{h['page']}: {h['text'][:160]!r}")
        print("method:", last_method())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
