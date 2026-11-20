"""Read a customer PO (or challan) PDF into a draft job card (``PoDraft``; never saved).

Deterministic path only: text is pulled with pdfplumber (fallback pypdf) and fields are found
with regexes, then the client is matched by name against the ``clients`` table. Anything the
PDF does not say is filled from the client's latest repeat job, with a warning and a low
confidence, so the draft is always a schema-valid ``JobCreate`` for PPIC to review.

Issue #18 adds the LLM path: implement :func:`llm_extract` (through ``core.llm.get_gateway()``);
its fields are merged in only where they beat the regex confidence. Money/metres are never
computed here.
"""
from __future__ import annotations

import io
import re
from datetime import date, timedelta
from difflib import SequenceMatcher
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.deps import T, today
from core.rules.dates import parse_erp_date
from core.rules.errors import RuleError


class PoReadError(ValueError):
    """The upload is not a readable PDF (API: 400)."""


CLIENT_MIN_SCORE = 0.6
DEFAULT_LEAD_DAYS = 14
DATE = r"(\d{4}-\d{1,2}-\d{1,2}|\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4})"
RE_PO_NO = re.compile(r"\b(?:P\.?\s?O\.?|Purchase\s+Order)\s*(?:No\.?|Number|#)?\s*[:\-]?\s*"
                      r"([A-Z0-9][A-Z0-9/\-_.]*\d[A-Z0-9/\-_.]*)", re.I)
RE_PO_DATE = re.compile(r"\b(?:PO\s+)?Date[d]?\s*[:\-]?\s*" + DATE, re.I)
RE_DUE = re.compile(r"\b(?:Delivery(?:\s+date)?|Deliver\s+by|Due(?:\s+date)?|Required\s+by)\b[^\n\d]{0,20}"
                    + DATE, re.I)
RE_QTY = re.compile(r"\b(?:Qty|Quantity|Order\s+qty)\s*[:\-]?\s*([\d,]{2,})", re.I)
RE_QTY_NOS = re.compile(r"\b(\d{1,3}(?:,\d{2,3})+|\d{3,})\s*(?:nos|pcs|labels)\b", re.I)
RE_RATE = re.compile(r"(?:\bRate\b|@)\s*[:\-]?\s*(?:Rs\.?|INR|₹)?\s*(\d+(?:\.\d+)?)", re.I)
RE_SIZE = re.compile(r"(\d+(?:\.\d+)?)\s*[x×*]\s*(\d+(?:\.\d+)?)\s*mm", re.I)
RE_JOB_CARD = re.compile(r"\bJC-\d{4,}\b")
RE_CLIENT_LINE = re.compile(r"^\s*(?:To|Buyer|Bill\s+to|Ship\s+to|Customer|Party|M/s\.?)\s*[:\-]?\s*(.+)$",
                            re.I | re.M)
RE_PRODUCT = re.compile(r"^\s*(?:Item|Product|Description)?\s*[:\-]?\s*(.*?\blabel\b)", re.I | re.M)


# ---------------------------------------------------------------- text extraction

def pdf_text(data: bytes) -> str:
    """All page text of a PDF. Raises PoReadError for a non-PDF or a PDF without text."""
    if not data or not data.lstrip()[:5].startswith(b"%PDF"):
        raise PoReadError("upload is not a PDF")
    text = ""
    try:
        import pdfplumber

        with pdfplumber.open(io.BytesIO(data)) as pdf:
            text = "\n".join((page.extract_text() or "") for page in pdf.pages)
    except Exception:  # noqa: BLE001 - fall back to pypdf on any pdfplumber failure
        try:
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(data))
            text = "\n".join((page.extract_text() or "") for page in reader.pages)
        except Exception as exc:  # noqa: BLE001
            raise PoReadError("the PDF could not be read") from exc
    if not text.strip():
        raise PoReadError("no text found in the PDF (scanned PDFs are not supported yet)")
    return text


# ---------------------------------------------------------------- LLM hook (issue #18)

def llm_extract(text: str, file_name: str) -> dict[str, dict] | None:
    """Hook for issue #18: return ``{field: {value, confidence, source_text}}`` or None.

    Must go through ``core.llm.get_gateway()`` and return None when the LLM is unavailable,
    so the deterministic draft below always works. Not wired to any model in this PR.
    """
    return None


# ---------------------------------------------------------------- field extraction

def _field(value: Any, confidence: float, source: str | None) -> dict:
    return {"value": value, "confidence": round(float(confidence), 2), "source_text": source}


def _date(raw: str) -> date | None:
    try:
        return parse_erp_date(raw)
    except RuleError:
        return None


def _match_client(db: Session, text: str) -> tuple[dict | None, str | None]:
    clients = T("clients")
    rows = db.execute(select(clients.c.id, clients.c.name)).all()
    candidates = [m.group(1).strip() for m in RE_CLIENT_LINE.finditer(text)]
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    low = text.lower()
    best: tuple[float, Any, str | None] = (0.0, None, None)
    for r in rows:
        name = (r.name or "").strip()
        if not name:
            continue
        if name.lower() in low:
            src = next((ln for ln in lines if name.lower() in ln.lower()), name)
            score = 0.97 if src in candidates or any(name.lower() in c.lower() for c in candidates) else 0.9
            if score > best[0]:
                best = (score, r, src)
            continue
        for c in candidates:
            head = c.split(",")[0].strip()
            score = SequenceMatcher(None, name.lower(), head.lower()).ratio()
            if score > best[0]:
                best = (score, r, c)
    score, row, src = best
    if row is None or score < CLIENT_MIN_SCORE:
        return None, candidates[0] if candidates else None
    return {"client_id": row.id, "client_name": row.name, "score": round(score, 4)}, src


def _repeat_job(db: Session, client_id: str | None, job_card: str | None, product: str | None) -> Any:
    jobs = T("jobs")
    if job_card:
        row = db.execute(select(jobs).where(jobs.c.job_card == job_card)).first()
        if row is not None:
            return row
    if not client_id:
        return None
    rows = db.execute(select(jobs).where(jobs.c.client_id == client_id)
                      .order_by(jobs.c.created_on.desc(), jobs.c.job_card.desc())).all()
    if product:
        words = {w for w in re.findall(r"[a-z0-9]+", product.lower()) if len(w) > 2}
        scored = sorted(rows, key=lambda r: -len(words & set(re.findall(r"[a-z0-9]+", (r.product or "").lower()))))
        if scored:
            return scored[0]
    return rows[0] if rows else None


def _match_item(db: Session, text: str) -> tuple[str | None, str | None]:
    """An item whose name (e.g. 'PP White 250 mm') or stock-head name appears in the text."""
    items = T("items")
    low = text.lower()
    rows = db.execute(select(items.c.id, items.c.name, items.c.width_mm)).all()
    for r in rows:
        if r.name and r.name.lower() in low:
            return r.id, r.name
    return None, None


def extract(db: Session, text: str, file_name: str) -> dict:
    """Build the ``PoDraft`` dict from PDF text."""
    fields: dict[str, dict] = {}
    warnings: list[str] = []

    client_match, client_src = _match_client(db, text)
    if client_match:
        fields["client_id"] = _field(client_match["client_id"], client_match["score"], client_src)
    else:
        warnings.append("Client not matched to the client master" + (f": '{client_src}'" if client_src else ""))

    m = RE_PO_NO.search(text)
    if m:
        fields["po_no"] = _field(m.group(1).rstrip(".,"), 0.95, m.group(0).strip())

    m = RE_PO_DATE.search(text)
    po_date = _date(m.group(1)) if m else None
    if po_date:
        fields["po_date"] = _field(po_date.isoformat(), 0.9, m.group(0).strip())
        if not re.match(r"\d{4}-", m.group(1)):
            warnings.append(f"Date {m.group(1)} parsed day-first as {po_date.isoformat()}")

    m = RE_DUE.search(text)
    due = _date(m.group(1)) if m else None
    if due:
        fields["due_date"] = _field(due.isoformat(), 0.8, m.group(0).strip())

    m = RE_QTY.search(text) or RE_QTY_NOS.search(text)
    if m:
        try:
            fields["order_qty"] = _field(int(m.group(1).replace(",", "")), 0.9, m.group(0).strip())
        except ValueError:
            pass

    m = RE_RATE.search(text)
    if m:
        fields["rate"] = _field(round(float(m.group(1)), 2), 0.85, m.group(0).strip())

    m = RE_SIZE.search(text)
    if m:
        size = f"{_num(m.group(1))} x {_num(m.group(2))} mm"
        fields["label_size"] = _field(size, 0.85, m.group(0).strip())

    m = RE_PRODUCT.search(text)
    if m and m.group(1).strip():
        product = re.sub(r"\s+", " ", m.group(1)).strip(" -:")
        fields["product"] = _field(product, 0.8, m.group(0).strip())

    item_id, item_src = _match_item(db, text)
    if item_id:
        fields["item_id"] = _field(item_id, 0.7, item_src)

    for key, f in (llm_extract(text, file_name) or {}).items():
        if f and f.get("value") is not None and f.get("confidence", 0) > fields.get(key, {}).get("confidence", 0):
            fields[key] = _field(f["value"], f.get("confidence", 0), f.get("source_text"))

    # ---- fill the rest from the client's repeat job, so PPIC only reviews
    jc = RE_JOB_CARD.search(text)
    client_id = fields.get("client_id", {}).get("value")
    product = fields.get("product", {}).get("value")
    rep = _repeat_job(db, client_id, jc.group(0) if jc else None, product)
    if rep is not None and not client_id and rep.client_id:
        client_id = rep.client_id
        fields["client_id"] = _field(client_id, 0.6, jc.group(0) if jc else None)
        warnings.append(f"Client taken from job {rep.job_card}")
    if rep is not None:
        for key, label in (("product", "product"), ("label_size", "label size"), ("rate", "rate"),
                           ("item_id", "paper"), ("order_qty", "quantity")):
            if key not in fields and getattr(rep, key, None) is not None:
                value = getattr(rep, key)
                value = round(float(value), 2) if key == "rate" else value
                fields[key] = _field(value, 0.5, None)
                warnings.append(f"{label.capitalize()} not on PO: taken from repeat job {rep.job_card}")
        warnings.append(f"Ups, repeat, machine and colours assumed from repeat job {rep.job_card}")

    po_date = _as_date(fields.get("po_date")) or today()
    if "po_date" not in fields:
        warnings.append(f"PO date not found: using today {po_date.isoformat()}")
    due = _as_date(fields.get("due_date"))
    if due is None:
        due = po_date + timedelta(days=DEFAULT_LEAD_DAYS)
        warnings.append(f"Delivery date not found: assumed {DEFAULT_LEAD_DAYS} days after PO date")
    if "po_no" not in fields:
        warnings.append("PO number not found: enter it before creating the job")
    for key in ("order_qty", "rate", "item_id", "product"):
        if key not in fields:
            warnings.append(f"{key} not found: enter it before creating the job")

    def val(key: str, default: Any) -> Any:
        v = fields.get(key, {}).get("value")
        return default if v is None else v

    draft = {
        "client_id": str(val("client_id", "")),
        "po_no": str(val("po_no", "")),
        "po_date": po_date.isoformat(),
        "product": str(val("product", "")),
        "label_size": str(val("label_size", "")),
        "order_qty": int(val("order_qty", 0)),
        "rate": round(float(val("rate", 0)), 2),
        "item_id": str(val("item_id", "")),
        "machine_id": (rep.machine_id if rep is not None else None) or "",
        "ups_across": int((rep.ups_across if rep is not None else None) or 1),
        "ups_along": int((rep.ups_along if rep is not None else None) or 1),
        "repeat_mm": float((rep.repeat_mm if rep is not None else None) or 0),
        "units": list((rep.units if rep is not None else None) or []),
        "due_date": due.isoformat(),
        "enquiry_id": None,
        "priority": "normal",
    }
    if not draft["machine_id"]:
        del draft["machine_id"]
    return {"saved": False, "file_name": file_name, "fields": fields, "client_match": client_match,
            "warnings": warnings, "draft": draft}


def _num(s: str) -> str:
    return s[:-2] if s.endswith(".0") else s


def _as_date(f: dict | None) -> date | None:
    if not f or not f.get("value"):
        return None
    try:
        return date.fromisoformat(str(f["value"]))
    except ValueError:
        return None


def read_po(db: Session, data: bytes, file_name: str) -> dict:
    """PDF bytes -> PoDraft dict. Raises PoReadError (400) for a non-PDF / unreadable file."""
    return extract(db, pdf_text(data), file_name or "upload.pdf")
