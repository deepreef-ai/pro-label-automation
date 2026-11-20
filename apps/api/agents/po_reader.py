"""LLM structured extraction of a customer PO (issue #18), used by ``app.services.po_reader``.

The model only *reads*: it returns the text it sees for each ``PoDraft`` field as strings, and
code parses dates and numbers and matches the client against the client master. Every call
goes through ``core.llm.get_gateway()`` (cloud mode anonymises known client names). Any
failure - no provider, bad JSON, nothing usable - returns ``None`` so the deterministic regex
reader stays the fallback.
"""
from __future__ import annotations

import logging
import re
from datetime import date
from difflib import SequenceMatcher
from typing import Any

from core.rules.dates import parse_erp_date
from core.rules.errors import RuleError

log = logging.getLogger(__name__)

MAX_TEXT = 6000  # characters of PO text sent to the model
CONF_SEEN = 0.75  # value found verbatim in the PDF text
CONF_UNSEEN = 0.5  # model answer not found in the text (likely reformatted)
CLIENT_MIN_SCORE = 0.6

FIELDS = ("po_no", "po_date", "due_date", "client_name", "product", "label_size", "order_qty", "rate", "material")
SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {k: {"type": ["string", "null"]} for k in FIELDS},
    "required": list(FIELDS),
}
PROMPT = (
    "You read purchase orders sent to a label-printing plant. From the PO text below, copy each "
    "field exactly as written in the text (do not calculate, convert or guess; use null when the "
    "PO does not say it):\n"
    "- po_no: the purchase order number\n"
    "- po_date: the PO date\n"
    "- due_date: the delivery / required-by date\n"
    "- client_name: the buyer company that issued the PO (not the supplier)\n"
    "- product: the label being ordered (e.g. 'Mango Juice 1L front label')\n"
    "- label_size: the label size, e.g. '80 x 120 mm'\n"
    "- order_qty: the quantity of labels\n"
    "- rate: the price per label\n"
    "- material: the label stock / paper, e.g. 'PP White 250 mm'\n\n"
    "PO text:\n"
)

RE_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")
RE_SIZE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:mm)?\s*[x×*X]\s*(\d+(?:\.\d+)?)\s*(?:mm)?")
RE_LAKH = re.compile(r"(\d+(?:\.\d+)?)\s*(lakh|lac|lakhs|k)\b", re.I)


def _clean(v: Any) -> str | None:
    if v is None:
        return None
    s = re.sub(r"\s+", " ", str(v)).strip(" :-\t")
    return s or None if s.lower() not in ("null", "none", "n/a", "na", "-") else None


def _seen(raw: str, text: str) -> bool:
    norm = lambda s: re.sub(r"\s+", " ", s).lower()  # noqa: E731
    return norm(raw) in norm(text)


def _date(raw: str) -> date | None:
    m = re.search(r"\d{4}-\d{1,2}-\d{1,2}|\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}", raw)
    candidates = [m.group(0)] if m else []
    candidates.append(raw)
    for c in candidates:
        try:
            return parse_erp_date(c)
        except (RuleError, ValueError, TypeError):
            continue
    return None


def _qty(raw: str) -> int | None:
    m = RE_LAKH.search(raw)
    if m:
        mult = 1000 if m.group(2).lower() == "k" else 100000
        return int(round(float(m.group(1)) * mult))
    m = RE_NUM.search(raw)
    if not m:
        return None
    try:
        v = float(m.group(0).replace(",", ""))
    except ValueError:
        return None
    return int(v) if v >= 1 and v == int(v) else None


def _rate(raw: str) -> float | None:
    m = RE_NUM.search(raw.replace("₹", " "))
    if not m:
        return None
    try:
        v = round(float(m.group(0).replace(",", "")), 2)
    except ValueError:
        return None
    return v if 0 < v < 1000 else None  # a per-label rate; a total value is not a rate


def _size(raw: str) -> str | None:
    m = RE_SIZE.search(raw)
    if not m:
        return None
    num = lambda s: s[:-2] if s.endswith(".0") else s  # noqa: E731
    return f"{num(m.group(1))} x {num(m.group(2))} mm"


def _client(raw: str, clients: list[dict]) -> tuple[str | None, float]:
    best: tuple[float, str | None] = (0.0, None)
    low = raw.lower()
    for c in clients:
        name = (c.get("name") or "").strip()
        if not name:
            continue
        score = 1.0 if name.lower() in low or low in name.lower() else SequenceMatcher(None, name.lower(), low).ratio()
        if score > best[0]:
            best = (score, c.get("id"))
    return (best[1], best[0]) if best[0] >= CLIENT_MIN_SCORE else (None, best[0])


def _field(value: Any, raw: str, text: str, scale: float = 1.0) -> dict:
    conf = (CONF_SEEN if _seen(raw, text) else CONF_UNSEEN) * scale
    return {"value": value, "confidence": round(conf, 2), "source_text": raw}


def extract_po(text: str, *, clients: list[dict], gateway=None) -> dict | None:
    """``{field: {value, confidence, source_text}}`` for the ``PoDraft`` fields the model found,
    or None when the LLM is unavailable / answers nothing usable.

    ``clients``: ``[{id, name}]`` from the client master (the model's buyer name is matched here).
    """
    if not text or not text.strip():
        return None
    try:
        if gateway is None:
            from core.llm import get_gateway

            gateway = get_gateway()
        result = gateway.complete([{"role": "user", "content": PROMPT + text[:MAX_TEXT]}],
                                  purpose="po_reader", json_schema=SCHEMA, cache=False)
        data = result.data
    except Exception as exc:  # noqa: BLE001 - LLMUnavailable or anything else -> regex fallback
        log.info("po_reader LLM path unavailable: %s", exc)
        return None
    if not isinstance(data, dict):
        return None

    raw = {k: _clean(data.get(k)) for k in FIELDS}
    out: dict[str, dict] = {}
    if raw["po_no"] and len(raw["po_no"]) <= 40 and re.search(r"\d", raw["po_no"]):
        out["po_no"] = _field(raw["po_no"], raw["po_no"], text)
    for key in ("po_date", "due_date"):
        if raw[key] and (d := _date(raw[key])) is not None:
            out[key] = _field(d.isoformat(), raw[key], text)
    if raw["client_name"]:
        cid, score = _client(raw["client_name"], clients)
        if cid:
            out["client_id"] = _field(cid, raw["client_name"], text, scale=min(score, 1.0))
    if raw["product"] and len(raw["product"]) <= 120:
        out["product"] = _field(raw["product"], raw["product"], text)
    if raw["label_size"] and (s := _size(raw["label_size"])):
        out["label_size"] = _field(s, raw["label_size"], text)
    if raw["order_qty"] and (q := _qty(raw["order_qty"])):
        out["order_qty"] = _field(q, raw["order_qty"], text)
    if raw["rate"] and (r := _rate(raw["rate"])) is not None:
        out["rate"] = _field(r, raw["rate"], text)
    if raw["material"]:
        out["material"] = _field(raw["material"], raw["material"], text)
    return out or None
