"""Text extraction from the client's documents (``data/raw/docs``) for the RAG index.

``list_documents(raw_dir)`` returns ``[{"source": filename, "page": n, "text": ...}]``:
one entry per PDF page (pypdf first, pdfplumber as fallback for pages pypdf cannot read)
and, for ``.txt``/``.md`` files, one entry per ~3,000-character block cut on blank lines.
Pages without text (scans/images) are skipped.

CLI: ``PYTHONPATH=apps/api python -m core.etl.docs --raw data/raw`` prints a per-file summary.
"""
from __future__ import annotations

import argparse
import logging
import re
from pathlib import Path

TXT_BLOCK = 3000
MIN_CHARS = 20

logging.getLogger("pypdf").setLevel(logging.ERROR)
logging.getLogger("pdfminer").setLevel(logging.ERROR)


def _norm(text: str) -> str:
    text = text.replace(" ", " ").replace("\r", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _pdf_pages(path: Path) -> list[tuple[int, str]]:
    texts: list[str | None] = []
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        for p in reader.pages:
            try:
                texts.append(p.extract_text() or "")
            except Exception:
                texts.append(None)
    except Exception:
        texts = []
    weak = [i for i, t in enumerate(texts) if not t or len(t.strip()) < MIN_CHARS]
    if not texts or weak:
        try:
            import pdfplumber

            with pdfplumber.open(str(path)) as pdf:
                if not texts:
                    texts = [None] * len(pdf.pages)
                    weak = list(range(len(pdf.pages)))
                for i in weak:
                    try:
                        texts[i] = pdf.pages[i].extract_text() or texts[i] or ""
                    except Exception:
                        pass
        except Exception:
            pass
    return [(i + 1, _norm(t)) for i, t in enumerate(texts) if t and len(_norm(t)) >= MIN_CHARS]


def _txt_blocks(path: Path) -> list[tuple[int, str]]:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    blocks, cur = [], ""
    for para in re.split(r"\n\s*\n", text.replace("\r", "")):
        if cur and len(cur) + len(para) > TXT_BLOCK:
            blocks.append(cur)
            cur = ""
        cur = f"{cur}\n\n{para}" if cur else para
    if cur.strip():
        blocks.append(cur)
    return [(i + 1, _norm(b)) for i, b in enumerate(blocks) if len(_norm(b)) >= MIN_CHARS]


def list_documents(raw_dir: str | Path) -> list[dict]:
    """Extract text from every PDF/TXT/MD in ``<raw_dir>/docs`` (or ``raw_dir`` itself)."""
    base = Path(raw_dir)
    folder = base / "docs" if (base / "docs").is_dir() else base
    out: list[dict] = []
    for path in sorted(folder.iterdir()):
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            parts = _pdf_pages(path)
        elif suffix in (".txt", ".md"):
            parts = _txt_blocks(path)
        else:
            continue
        out.extend({"source": path.name, "page": n, "text": t} for n, t in parts)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Extract document text for the RAG index")
    ap.add_argument("--raw", default="data/raw")
    a = ap.parse_args(argv)
    docs = list_documents(a.raw)
    summary: dict[str, list[int]] = {}
    for d in docs:
        s = summary.setdefault(d["source"], [0, 0])
        s[0] += 1
        s[1] += len(d["text"])
    for name, (pages, chars) in summary.items():
        print(f"{name:<60}{pages:>5} pages{chars:>9} chars")
    print(f"total: {len(docs)} chunks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
