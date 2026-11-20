"""Chat tools (SPEC 4b). Every tool is ``read`` or ``draft``; none ever writes.

* ``read`` tools only call ``ctx.api.get`` (the public HTTP API with the caller's ``X-Role``)
  or the local RAG index, and return ``{"data": ..., "sources": [{"label", "link"}]}``.
* ``draft`` tools may read, but never call ``ctx.api.post``/``put``. They return
  ``{"type": "draft", "entity", "endpoint", "body", "payload", "summary"}``; the user confirms
  it in the chat panel, which then calls the endpoint itself. ``payload`` mirrors ``body``
  (the contract's ``ChatAction`` uses ``payload``).

Money/stock numbers come from the API (computed by ``core.rules`` there); tools only pick
and format them.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any
from urllib.parse import quote, urlencode

# ----------------------------------------------------------------- types


@dataclass
class ToolContext:
    role: str = "owner"
    api: Any = None


@dataclass
class Tool:
    name: str
    description: str
    mode: str  # "read" | "draft"
    fn: Callable[[dict, ToolContext], dict]
    args: dict = field(default_factory=dict)  # arg name -> short description (for the LLM prompt)
    roles: set | None = None  # roles allowed to *confirm* the draft (None = all)

    def run(self, args: dict, ctx: ToolContext) -> dict:
        return self.fn(dict(args or {}), ctx)


# ----------------------------------------------------------------- helpers

JOB_RE = re.compile(r"\bJC[-\s]?(\d{3,5})\b", re.I)


def job_card_from(text: Any) -> str | None:
    m = JOB_RE.search(str(text or ""))
    return f"JC-{m.group(1)}" if m else None


def _get(ctx: ToolContext, path: str) -> dict:
    out = ctx.api.get(path)
    if isinstance(out, list):
        return {"items": out, "total": len(out)}
    return out if isinstance(out, dict) else {"value": out}


def _items(data: Any, *keys: str) -> list:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in (*keys, "items", "results", "clients"):
            v = data.get(k)
            if isinstance(v, list):
                return v
    return []


def _q(path: str, **params: Any) -> str:
    clean = {k: v for k, v in params.items() if v not in (None, "")}
    return f"{path}?{urlencode(clean)}" if clean else path


def _src(label: str, link: str | None) -> dict:
    return {"label": label, "link": link}


def _norm_name(s: Any) -> str:
    s = str(s or "").lower()
    s = re.sub(r"\b(pvt|private|ltd|limited|co|company|inc|llp|the|m/s)\b\.?", " ", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _match(rows: list, query: Any, id_key: str = "id", name_key: str = "name") -> dict | None:
    """Find a master row by exact id, normalised name, or word overlap."""
    if query in (None, ""):
        return None
    q = str(query).strip()
    for r in rows:
        if str(r.get(id_key, "")).lower() == q.lower():
            return r
    nq = _norm_name(q)
    if not nq:
        return None
    for r in rows:
        if _norm_name(r.get(name_key)) == nq:
            return r
    for r in rows:
        nr = _norm_name(r.get(name_key))
        if nr and (nq in nr or nr in nq):
            return r
    best, score = None, 0
    words = set(nq.split())
    for r in rows:
        overlap = len(words & set(_norm_name(r.get(name_key)).split()))
        if overlap > score:
            best, score = r, overlap
    return best if score >= max(1, min(2, len(words))) else None


def find_client(ctx: ToolContext, query: Any) -> dict | None:
    rows = _items(_get(ctx, "/api/clients"))
    return _match(rows, query)


def _arg(args: dict, *names: str, default: Any = None) -> Any:
    for n in names:
        v = args.get(n)
        if v not in (None, ""):
            return v
    return default


def inr(value: Any) -> str:
    """Indian grouping: 1234567.5 -> 'Rs 12,34,567.50' (formatting only, no maths)."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    neg = v < 0
    whole, frac = f"{abs(v):.2f}".split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    text = f"Rs {whole}" + ("" if frac == "00" else f".{frac}")
    return f"-{text}" if neg else text


def pct(value: Any) -> str:
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return str(value)


# ----------------------------------------------------------------- read tools


def _search(args: dict, ctx: ToolContext) -> dict:
    q = str(_arg(args, "q", "query", "text", default=""))
    data = _get(ctx, _q("/api/search", q=q))
    return {"data": data, "sources": [_src(f"Search: {q}", None)]}


def _get_job(args: dict, ctx: ToolContext) -> dict:
    jc = job_card_from(_arg(args, "job_card", "job_id", "id", "job_card_id", "q", default=""))
    if not jc:
        return {"error": "need a job card like JC-1301"}
    job = _get(ctx, f"/api/jobs/{jc}")
    out: dict = {"job": job}
    if args.get("include_360", True):
        out["job_360"] = _get(ctx, f"/api/jobs/{jc}/360")
    return {"data": out, "sources": [_src(f"Job {jc}", f"/jobs/{jc}")]}


def _list_debtors(args: dict, ctx: ToolContext) -> dict:
    data = _get(ctx, "/api/debtors")
    status = str(_arg(args, "status", "filter", default="")).lower()
    rows = _items(data, "clients")
    if status in ("at_risk", "locked", "ok"):
        rows = [r for r in rows if r.get("lock_status") == status]
    elif status in ("risk", "lock", "locking"):
        rows = [r for r in rows if r.get("lock_status") in ("at_risk", "locked")]
    keep = ("client_id", "client_name", "outstanding", "max_days_past_due", "lock_status",
            "locks_on", "locked_since", "promise", "oldest_due_date")
    slim = [{k: r.get(k) for k in keep if k in r} for r in rows]
    return {
        "data": {"as_of": data.get("as_of"), "grace_days": data.get("grace_days"),
                 "totals": data.get("totals"), "clients": slim},
        "sources": [_src("Debtors & lock status", "/money?tab=debtors")],
    }


def _get_client(args: dict, ctx: ToolContext) -> dict:
    q = _arg(args, "client_id", "client", "client_name", "q", "query")
    client = find_client(ctx, q)
    if not client:
        return {"error": f"client {q!r} not found"}
    detail = _get(ctx, f"/api/clients/{quote(str(client['id']))}")
    return {"data": detail, "sources": [_src(f"Client {client.get('name')}",
                                              f"/money?tab=debtors&client={client['id']}")]}


def _dashboard(args: dict, ctx: ToolContext) -> dict:
    period = str(_arg(args, "period", default="month"))
    if period not in ("today", "month", "year"):
        period = "month"
    data = _get(ctx, _q("/api/dashboard/summary", period=period))
    return {"data": data, "sources": [_src(f"Owner dashboard ({period})", "/")]}


def _alerts(args: dict, ctx: ToolContext) -> dict:
    return {"data": _get(ctx, "/api/alerts"), "sources": [_src("Alerts", "/")]}


def _explain_flag(args: dict, ctx: ToolContext) -> dict:
    jc = job_card_from(_arg(args, "job_card", "job_id", "id", "q", default=""))
    if not jc:
        return {"error": "need a job card like JC-1240"}
    job = _get(ctx, f"/api/jobs/{jc}")
    j360 = _get(ctx, f"/api/jobs/{jc}/360")
    checks = j360.get("checks") if isinstance(j360.get("checks"), list) else []
    findings = _items(_get(ctx, _q("/api/agents/findings", status="open")))
    related = [f for f in findings if jc in str(f.get("title", "")) + str(f.get("detail", ""))]
    keep = ("job_card", "client_name", "product", "machine_name", "required_m", "planned_m",
            "issued_m", "printed_qty", "order_qty", "qc_approved", "status", "flags")
    data = {
        "job": {k: job.get(k) for k in keep if k in job},
        "checks": checks,
        "runs": (j360.get("runs") or [])[:6] if isinstance(j360.get("runs"), list) else [],
        "findings": [{k: f.get(k) for k in ("id", "agent", "severity", "title", "detail")}
                     for f in related],
    }
    sources = [_src(f"Job {jc} 360", f"/jobs/{jc}")]
    sources += [_src(f"Finding {f.get('id')}", "/agents") for f in related]
    return {"data": data, "sources": sources}


def _data_quality(args: dict, ctx: ToolContext) -> dict:
    return {"data": _get(ctx, "/api/store/data-quality"),
            "sources": [_src("Store data quality", "/store?tab=data-quality")]}


def _findings(args: dict, ctx: ToolContext) -> dict:
    status = str(_arg(args, "status", default="open"))
    if status not in ("open", "done", "rejected"):
        status = "open"
    data = _get(ctx, _q("/api/agents/findings", status=status))
    agent = _arg(args, "agent")
    rows = _items(data)
    if agent:
        rows = [f for f in rows if f.get("agent") == agent]
    slim = [{k: f.get(k) for k in ("id", "agent", "severity", "title", "detail", "status")}
            for f in rows[:15]]
    return {"data": {"status": status, "items": slim}, "sources": [_src("Agents Center", "/agents")]}


def _pnl(args: dict, ctx: ToolContext) -> dict:
    month = _arg(args, "month")
    if not (isinstance(month, str) and re.fullmatch(r"\d{4}-\d{2}", month)):
        month = None
    data = _get(ctx, _q("/api/pnl", month=month))
    return {"data": data, "sources": [_src(f"P&L {month or 'latest'}", "/money?tab=pnl")]}


def _stock(args: dict, ctx: ToolContext) -> dict:
    data = _get(ctx, "/api/store/stock")
    item = _arg(args, "item", "item_name", "q", "query")
    rows = _items(data)
    if item and rows:
        n = _norm_name(item)
        hit = [r for r in rows if n and n in _norm_name(r.get("item_name") or r.get("name"))]
        rows = hit or rows
    return {"data": {"items": rows[:20]}, "sources": [_src("Store stock", "/store")]}


def _rag_search(args: dict, ctx: ToolContext) -> dict:
    from chat import rag

    q = str(_arg(args, "query", "q", "text", default=""))
    hits = rag.search(q, k=int(args.get("k") or 4)) if q else []
    sources, seen = [], set()
    for h in hits:
        label = f"{h['source']}" + (f" p.{h['page']}" if h.get("page") else "")
        if label not in seen:
            seen.add(label)
            sources.append(_src(label, None))
    return {"data": {"query": q, "hits": hits, "method": rag.last_method()}, "sources": sources}


# ----------------------------------------------------------------- draft tools


def _draft(entity: str, endpoint: str, body: dict, summary: str, **extra: Any) -> dict:
    out = {"type": "draft", "entity": entity, "endpoint": endpoint, "body": body,
           "payload": body, "summary": summary}
    out.update(extra)
    return out


REMINDER_EN = (
    "Dear {contact}, this is a gentle reminder from Pro Labels. {client} has {amount} outstanding"
    "{due}. Kindly arrange payment at the earliest so dispatches continue without a hold. "
    "Thank you. - Accounts, Pro Labels"
)
REMINDER_HI = (
    "नमस्ते {contact} जी, Pro Labels की ओर से विनम्र याद-दहानी: {client} के खाते में {amount} बकाया है"
    "{due}। कृपया जल्द से जल्द भुगतान करें ताकि डिस्पैच बिना रुकावट चलता रहे। धन्यवाद। - अकाउंट्स, Pro Labels"
)


def _draft_reminder(args: dict, ctx: ToolContext) -> dict:
    q = _arg(args, "client_id", "client", "client_name", "query", "q")
    lang = str(_arg(args, "lang", "language", default="en")).lower()
    hindi = lang.startswith("hi")
    client = find_client(ctx, q) or {}
    client_id = client.get("id") or (str(q) if q is not None else "")
    name = client.get("name") or (str(q) if q else "the client")
    detail = _get(ctx, f"/api/clients/{quote(str(client_id))}") if client.get("id") else {}
    info = detail.get("client") if isinstance(detail.get("client"), dict) else client
    contact = (info or {}).get("contact") or ("ग्राहक" if hindi else "Sir/Madam")
    unpaid = [i for i in _items(detail, "invoices") if i.get("status") != "paid"
              and (i.get("outstanding") or 0) > 0]
    amount = inr((info or {}).get("outstanding", 0)) if info else "the pending amount"
    due = ""
    if unpaid:
        first = sorted(unpaid, key=lambda i: str(i.get("due_date")))[0]
        due = (f" (बिल {first.get('id')}, देय तिथि {first.get('due_date')})" if hindi
               else f" (invoice {first.get('id')}, due {first.get('due_date')})")
    text = (REMINDER_HI if hindi else REMINDER_EN).format(
        contact=contact, client=name, amount=amount, due=due)
    body = {
        "date": date.today().isoformat(),
        "client_id": str(client_id),
        "invoice_ids": [i.get("id") for i in unpaid],
        "mode": "whatsapp",
        "contact": (info or {}).get("contact") or "",
        "note": text,
        "promise_date": None,
        "promise_amount": None,
        "next_follow_up": None,
    }
    summary = f"Log a WhatsApp payment reminder to {name} ({'Hindi' if hindi else 'English'})"
    return _draft("collection", "/api/collections", body, summary, text=text, lang="hi" if hindi else "en")


def _draft_grn(args: dict, ctx: ToolContext) -> dict:
    vendors = _items(_get(ctx, "/api/vendors"))
    items = _items(_get(ctx, "/api/items"))
    vq = _arg(args, "vendor_id", "vendor", "vendor_name")
    iq = _arg(args, "item_id", "item", "item_name")
    vendor = _match(vendors, vq) or {}
    item = _match(items, iq) or {}
    rolls = _arg(args, "rolls")
    qty = _arg(args, "qty", "quantity", default=0)
    roll_lengths: list = []
    try:
        if rolls:
            length = float(_arg(args, "roll_length_m", default=1000))
            roll_lengths = [length] * int(float(rolls))
            qty = sum(roll_lengths)
        qty = float(qty)
    except (TypeError, ValueError):
        qty = 0.0
    body = {
        "date": str(_arg(args, "date", default=date.today().isoformat())),
        "vendor_id": str(vendor.get("id") or vq or ""),
        "bill_no": str(_arg(args, "bill_no", default="")),
        "item_id": str(item.get("id") or iq or ""),
        "qty": qty,
        "rate": float(_arg(args, "rate", default=item.get("rate") or 0) or 0),
    }
    if roll_lengths:
        body["roll_lengths_m"] = roll_lengths
    what = f"{int(len(roll_lengths))} rolls" if roll_lengths else f"{qty:g} {item.get('uom', 'units')}"
    summary = (f"Record GRN: {what} {item.get('name') or iq or 'item'} from "
               f"{vendor.get('name') or vq or 'vendor'}")
    notes = []
    if not vendor:
        notes.append(f"vendor {vq!r} not found in masters")
    if not item:
        notes.append(f"item {iq!r} not found in masters")
    if roll_lengths:
        notes.append(f"assumes {roll_lengths[0]:g} m per roll")
    if not body["bill_no"]:
        notes.append("add the bill number")
    if notes:
        summary += " (" + "; ".join(notes) + ")"
    return _draft("grn", "/api/store/grns", body, summary)


def _draft_release_lock(args: dict, ctx: ToolContext) -> dict:
    q = _arg(args, "client_id", "client", "client_name", "query", "q")
    client = find_client(ctx, q) or {}
    cid = str(client.get("id") or q or "")
    name = client.get("name") or (str(q) if q else "client")
    body = {"reason": str(_arg(args, "reason", default="Released by owner after payment commitment"))}
    endpoint = f"/api/clients/{quote(cid)}/release-lock"
    if ctx.role != "owner":
        return _draft("release_lock", endpoint, body,
                      f"Only the owner can release the lock on {name}; ask the owner to do it.",
                      allowed=False,
                      refusal=f"Only the owner can release a client lock. You are signed in as "
                              f"'{ctx.role}', so I can't prepare this for you; please ask the owner.")
    return _draft("release_lock", endpoint, body,
                  f"Release the credit lock on {name} (logged with time and reason)", allowed=True)


# ----------------------------------------------------------------- registry

_ALL = [
    Tool("search", "Global search across jobs, clients, invoices, challans.", "read", _search,
         {"q": "search text"}),
    Tool("get_job", "One job card with its 360 view (design, runs, QC, dispatch, invoices, cost, checks).",
         "read", _get_job, {"job_card": "JC-####"}),
    Tool("list_debtors", "Debtors with outstanding, ageing and lock status (at_risk clients lock on "
         "'locks_on').", "read", _list_debtors, {"status": "at_risk | locked | ok | (empty = all)"}),
    Tool("get_client", "One client with invoices, jobs, collections and lock log.", "read", _get_client,
         {"client": "client name or id"}),
    Tool("dashboard_summary", "Owner KPIs: revenue, profit, margin, cash, OEE, receivables.", "read",
         _dashboard, {"period": "today | month | year"}),
    Tool("alerts", "Current alerts needing attention.", "read", _alerts, {}),
    Tool("explain_flag", "Why a job is flagged (wastage, material, over-production, QC) with rule "
         "checks, runs and agent findings.", "read", _explain_flag, {"job_card": "JC-####"}),
    Tool("store_data_quality", "ERP import quality: issue lines without job card, date fixes.", "read",
         _data_quality, {}),
    Tool("agent_findings", "AI agent findings.", "read", _findings,
         {"status": "open | done | rejected", "agent": "optional agent name"}),
    Tool("pnl", "Monthly profit & loss, system vs Tally.", "read", _pnl, {"month": "YYYY-MM"}),
    Tool("store_stock", "Stock by item.", "read", _stock, {"item": "optional item name"}),
    Tool("rag_search", "Search the company's documents / system guide for how-to and policy answers.",
         "read", _rag_search, {"query": "question"}),
    Tool("draft_reminder", "Draft a payment reminder (WhatsApp text) for a client, English or Hindi.",
         "draft", _draft_reminder, {"client": "client name or id", "lang": "en | hi"}),
    Tool("draft_grn", "Draft a goods receipt (GRN) entry.", "draft", _draft_grn,
         {"vendor": "vendor name", "item": "item name", "qty": "metres", "rolls": "number of rolls",
          "rate": "optional rate", "bill_no": "optional bill number"}),
    Tool("draft_release_lock", "Draft releasing a client's credit lock (owner only).", "draft",
         _draft_release_lock, {"client": "client name or id", "reason": "why"}, roles={"owner"}),
]

TOOLS: dict[str, Tool] = {t.name: t for t in _ALL}


def describe_tools() -> str:
    lines = []
    for t in _ALL:
        args = ", ".join(f"{k}: {v}" for k, v in t.args.items()) or "none"
        lines.append(f"- {t.name} [{t.mode}]: {t.description} Args: {args}")
    return "\n".join(lines)
