"""Marketing read model: enquiry rows as contract JSON and the monthly marketing summary.

Money maths (quote value, invoice taxable) goes through ``core.rules.money`` (CLAUDE.md).
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.deps import T, today
from app.serialize import jsonable, money
from core.rules import money as M

ENQUIRY_STATUSES = ("new", "quoted", "won", "lost")
SOURCES = ("phone", "email", "whatsapp", "visit", "repeat", "website")

# Monthly sales targets in rupees. The schema has no targets table (contract/schema.md), so the
# demo targets live here; they match contract/fixtures/marketing_summary.json.
TARGETS: dict[str, Decimal] = {
    "Rohit Mehra": Decimal("3200000.00"),
    "Pooja Iyer": Decimal("2800000.00"),
}
HOUSE = next(iter(TARGETS))  # revenue that no enquiry explains is credited to the first salesperson


def quote_value(qty, rate) -> Decimal:
    """Quote value = qty * rate (schema.md quotes), via the PO value rule."""
    return M.po_value(qty or 0, rate or 0)


def _client_names(db: Session) -> dict[str, str]:
    c = T("clients")
    return {cid: name for cid, name in db.execute(select(c.c.id, c.c.name))}


def _quotes_by_enquiry(db: Session) -> dict[str, dict]:
    """Latest quote per enquiry (by date, then id)."""
    q = T("quotes")
    out: dict[str, dict] = {}
    for row in db.execute(select(q).order_by(q.c.date, q.c.id)):
        m = row._mapping
        if m["enquiry_id"]:
            out[m["enquiry_id"]] = dict(m)
    return out


def _jobs_by_enquiry(db: Session) -> dict[str, str]:
    j = T("jobs")
    out: dict[str, str] = {}
    rows = db.execute(select(j.c.enquiry_id, j.c.job_card).where(j.c.enquiry_id.is_not(None))
                      .order_by(j.c.job_card))
    for eid, jc in rows:
        out.setdefault(eid, jc)
    return out


def enquiry_json(row, clients: dict[str, str], quotes: dict[str, dict], jobs: dict[str, str]) -> dict:
    m = row._mapping if hasattr(row, "_mapping") else row
    quote = quotes.get(m["id"])
    client_name = clients.get(m["client_id"]) if m["client_id"] else None
    source = m["source"] if m["source"] in SOURCES else "phone"
    return {
        "id": m["id"],
        "date": jsonable(m["date"]),
        "client_id": m["client_id"],
        "client_name": client_name or m["prospect_name"] or "",
        "product": m["product"] or "",
        "label_size": m["label_size"] or "",
        "qty": int(m["qty"] or 0),
        "material": m["material"] or "",
        "colours": int(m["colours"] or 0),
        "finish": m["finish"] or "None",
        "source": source,
        "assigned_to": m["assigned_to"] or "",
        "status": m["status"] if m["status"] in ENQUIRY_STATUSES else "new",
        "quote_id": quote["id"] if quote else None,
        "value": money(quote_value(quote["qty"], quote["rate"])) if quote else None,
        "lost_reason": m["lost_reason"],
        "follow_up_on": jsonable(m["follow_up_on"]),
        "job_card": jobs.get(m["id"]),
        "is_demo": bool(m["is_demo"]),
    }


def list_enquiries(db: Session, status: str | None = None) -> list[dict]:
    e = T("enquiries")
    stmt = select(e).order_by(e.c.date, e.c.id)
    if status:
        stmt = stmt.where(e.c.status == status)
    rows = db.execute(stmt).all()
    clients, quotes, jobs = _client_names(db), _quotes_by_enquiry(db), _jobs_by_enquiry(db)
    return [enquiry_json(r, clients, quotes, jobs) for r in rows]


def get_enquiry(db: Session, enquiry_id: str) -> dict | None:
    e = T("enquiries")
    row = db.execute(select(e).where(e.c.id == enquiry_id)).first()
    if row is None:
        return None
    return enquiry_json(row, _client_names(db), _quotes_by_enquiry(db), _jobs_by_enquiry(db))


def quote_json(row) -> dict:
    m = row._mapping if hasattr(row, "_mapping") else row
    value = quote_value(m["qty"], m["rate"])
    cost = Decimal(str(m["cost_estimate"] or 0))
    margin = ((value - cost) / value).quantize(Decimal("0.0001")) if value else Decimal("0")
    return {
        "id": m["id"],
        "enquiry_id": m["enquiry_id"],
        "date": jsonable(m["date"]),
        "qty": int(m["qty"] or 0),
        "rate": money(m["rate"]),
        "value": money(value),
        "cost_estimate": money(cost),
        "margin_pct": float(margin),
        "valid_until": jsonable(m["valid_until"]),
        "notes": m["notes"] or "",
        "status": m["status"] or "sent",
        "is_demo": bool(m["is_demo"]),
    }


def cost_ratio(db: Session) -> Decimal:
    """Cost / value across past quotes: the demo costing basis for a new quote's cost estimate."""
    q = T("quotes")
    value = cost = Decimal("0")
    for qty, rate, ce in db.execute(select(q.c.qty, q.c.rate, q.c.cost_estimate)):
        if qty and rate and ce:
            value += quote_value(qty, rate)
            cost += Decimal(str(ce))
    return (cost / value) if value else Decimal("0.72")


def _month_bounds(day: date) -> tuple[date, date]:
    start = day.replace(day=1)
    end = start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(month=start.month + 1)
    return start, end


def _lost_reason_label(reason: str | None) -> str:
    text = (reason or "").split(":", 1)[0].strip()
    return text or "Not given"


def summary(db: Session) -> dict:
    day = today()
    start, end = _month_bounds(day)
    e, j, inv = T("enquiries"), T("jobs"), T("invoices")

    enquiries = [dict(r._mapping) for r in db.execute(select(e).order_by(e.c.date, e.c.id))]
    month_enq = [x for x in enquiries if x["date"] and start <= x["date"] < end]

    funnel = {s: 0 for s in ENQUIRY_STATUSES}
    for x in month_enq:
        if x["status"] in funnel:
            funnel[x["status"]] += 1
    decided = funnel["won"] + funnel["lost"]
    win_rate = round(funnel["won"] / decided, 4) if decided else 0.0

    quotes = _quotes_by_enquiry(db)
    pipeline = sum((quote_value(quotes[x["id"]]["qty"], quotes[x["id"]]["rate"])
                    for x in enquiries if x["status"] == "quoted" and x["id"] in quotes), Decimal("0"))

    # Achieved = invoiced taxable value this month (same basis as the dashboard's revenue),
    # credited to the salesperson of the job's enquiry, else of the client's latest enquiry.
    by_enquiry = {x["id"]: x["assigned_to"] for x in enquiries}
    by_client: dict[str, str] = {}
    for x in enquiries:  # ordered by date, so the latest enquiry wins
        if x["client_id"] and x["assigned_to"]:
            by_client[x["client_id"]] = x["assigned_to"]
    job_enq = {jc: eid for jc, eid in db.execute(select(j.c.job_card, j.c.enquiry_id))}
    achieved_by: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    inv_rows = db.execute(
        select(inv.c.job_card, inv.c.client_id, inv.c.qty, inv.c.rate, inv.c.status)
        .where(inv.c.date >= start, inv.c.date < end)
    )
    for jc, client_id, qty, rate, status in inv_rows:
        if status == "draft":
            continue
        taxable = M.invoice_amounts(qty or 0, rate or 0).taxable
        person = by_enquiry.get(job_enq.get(jc) or "") or by_client.get(client_id or "") or HOUSE
        achieved_by[person] += taxable

    names = list(TARGETS)
    for x in month_enq:
        if x["assigned_to"] and x["assigned_to"] not in names:
            names.append(x["assigned_to"])
    for name in achieved_by:
        if name not in names:
            names.append(name)
    by_person = []
    for name in names:
        mine = [x for x in month_enq if x["assigned_to"] == name]
        by_person.append({
            "name": name,
            "target": money(TARGETS.get(name, 0)),
            "achieved": money(achieved_by.get(name, 0)),
            "enquiries": len(mine),
            "won": sum(1 for x in mine if x["status"] == "won"),
        })

    target = sum(TARGETS.values(), Decimal("0"))
    achieved = sum(achieved_by.values(), Decimal("0"))
    reasons = Counter(_lost_reason_label(x["lost_reason"]) for x in enquiries if x["status"] == "lost")
    lost_reasons = [{"reason": r, "count": n} for r, n in sorted(reasons.items(), key=lambda kv: (-kv[1], kv[0]))]

    return {
        "month": start.strftime("%Y-%m"),
        "target": money(target),
        "achieved": money(achieved),
        "achievement_pct": float((achieved / target).quantize(Decimal("0.0001"))) if target else 0.0,
        "funnel": funnel,
        "win_rate": win_rate,
        "pipeline_value": money(pipeline),
        "by_person": by_person,
        "lost_reasons": lost_reasons,
    }
