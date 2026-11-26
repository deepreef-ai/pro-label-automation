"""Receivables: invoices, draft invoice from a challan, debtors ageing and the collection diary.

SPEC 2 (invoice, due date, lock, ageing) and SPEC 3 "Money". Issue #17 (A3).

Invoice rows, ageing buckets and the lock state come from ``services.clients``
(``invoice_dicts``, ``ageing``, ``lock_state``), so the debtors page, the client page and the
dispatch lock guard always agree. All money maths is ``core.rules.money``.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit import audit, next_id
from app.deps import T, bad_request, conflict, not_found, today
from app.serialize import jsonable, money
from app.services import clients as cl_svc
from core.rules import money as M

INVOICE_STATUSES = ("draft", "open", "part_paid", "paid")
COLLECTION_MODES = ("call", "whatsapp", "email", "visit")


def _gst_rate(db: Session) -> Decimal:
    from app.routers.shell import load_settings  # local import: routers import services

    g = load_settings(db).get("gst_rate")
    return Decimal(str(g)) if g is not None else M.DEFAULTS.gst_rate


def _sum(values) -> float:
    return float(sum((Decimal(str(v)) for v in values), Decimal("0.00")))


# ---------------------------------------------------------------- invoices


def list_invoices(db: Session, *, status: str | None = None, client_id: str | None = None) -> dict:
    """``InvoiceListResponse``: invoices in date order; total_outstanding excludes drafts."""
    if status is not None and status not in INVOICE_STATUSES:
        raise bad_request(f"status: must be one of {', '.join(INVOICE_STATUSES)}")
    ids = None
    if client_id is not None:
        client_id = client_id.strip().upper()
        if cl_svc.get_client_row(db, client_id) is None:
            raise bad_request(f"client_id: unknown client {client_id}")
        ids = [client_id]
    items = cl_svc.invoice_dicts(db, ids)
    if status is not None:
        items = [i for i in items if i["status"] == status]
    total = _sum(i["outstanding"] for i in items if i["status"] != "draft")
    return {"total_outstanding": total, "items": items}


def get_invoice(db: Session, invoice_id: str, client_id: str) -> dict | None:
    return next((i for i in cl_svc.invoice_dicts(db, [client_id]) if i["id"] == invoice_id), None)


def issue_invoice(db: Session, invoice_id: str, role: str) -> dict:
    """Draft -> open (``POST /api/invoices/{id}/issue``). Only an issued invoice counts in debtors,
    ageing, locks and revenue. 404 unknown (or another company's) invoice, 409 if not a draft."""
    inv_id = invoice_id.strip().upper()
    inv = T("invoices")
    row = db.execute(select(inv.c.status, inv.c.client_id).where(inv.c.id == inv_id)).first()
    if row is None:
        raise not_found("invoice", inv_id)
    if row.status != "draft":
        raise conflict(f"invoice {inv_id} is {row.status}; only a draft can be issued")
    db.execute(inv.update().where(inv.c.id == inv_id).values(status="open"))
    audit(db, role=role, action="invoice_issue", entity="invoice", entity_id=inv_id,
          before={"status": "draft"}, after={"status": "open"})
    db.commit()
    return get_invoice(db, inv_id, row.client_id) or {}


def draft_from_dispatch(db: Session, dispatch_id: str, role: str) -> dict:
    """Draft invoice for one challan: qty from the challan, rate from the job, GST at the
    settings rate, dated today; due date = today + client credit days. 404 unknown challan,
    409 if the challan already has an invoice."""
    dc_id = dispatch_id.strip().upper()
    d, jobs, inv = T("dispatches"), T("jobs"), T("invoices")
    row = db.execute(
        select(d.c.id, d.c.qty, d.c.job_card, jobs.c.client_id, jobs.c.rate)
        .select_from(d).join(jobs, jobs.c.job_card == d.c.job_card, isouter=True)
        .where(d.c.id == dc_id)
    ).first()
    if row is None:
        raise not_found("dispatch", dc_id)
    existing = db.execute(select(inv.c.id).where(inv.c.dispatch_id == dc_id)).scalar()
    if existing is not None:
        raise conflict(f"challan {dc_id} is already invoiced ({existing}); a challan is invoiced only once")
    if row.client_id is None or row.rate is None:
        raise bad_request(f"challan {dc_id}: job {row.job_card} not found")

    gst_rate = _gst_rate(db)
    qty, rate = int(row.qty or 0), Decimal(str(row.rate))
    amounts = M.invoice_amounts(qty, rate, gst_rate)  # validates qty/rate/GST before saving
    inv_id = next_id(db, "invoices", "INV", 4)
    values: dict[str, Any] = {
        "id": inv_id, "date": today(), "client_id": row.client_id, "job_card": row.job_card,
        "dispatch_id": dc_id, "qty": qty, "rate": rate, "gst_rate": gst_rate, "status": "draft",
        "source": "app", "is_demo": False,
    }
    db.execute(inv.insert().values({k: v for k, v in values.items() if k in inv.c}))
    audit(db, role=role, action="invoice_draft", entity="invoice", entity_id=inv_id,
          after={**values, "taxable": amounts.taxable, "gst": amounts.gst, "total": amounts.total})
    from app.services import job_status

    job_status.advance(db, row.job_card, "invoiced", role=role, reason=f"invoice {inv_id}")
    db.commit()
    return get_invoice(db, inv_id, row.client_id) or {}


# ---------------------------------------------------------------- debtors


def _last_receipts(db: Session) -> dict[str, date]:
    r = T("receipts")
    return {cid: d for cid, d in db.execute(select(r.c.client_id, func.max(r.c.date)).group_by(r.c.client_id))}


def _open_promises(collections: list[dict]) -> dict[str, dict]:
    """Earliest open promise per client: ``{date, amount}``."""
    out: dict[str, dict] = {}
    for c in sorted(collections, key=lambda c: (c["promise_date"] or "", c["id"])):
        if c["status"] == "open" and c["promise_date"] and c["client_id"] not in out:
            out[c["client_id"]] = {"date": c["promise_date"], "amount": money(c["promise_amount"])}
    return out


def debtors(db: Session) -> dict:
    """``Debtors``: per-client outstanding by ageing bucket with the shared lock state."""
    cl = T("clients")
    clients = db.execute(select(cl.c.id, cl.c.name, cl.c.credit_days, cl.c.lock_override_until)).all()
    as_of, grace = today(), cl_svc._grace_days(db)
    by_client: dict[str, list[dict]] = defaultdict(list)
    for i in cl_svc.invoice_dicts(db, None, as_of=as_of, credit_days={c.id: c.credit_days for c in clients}):
        by_client[i["client_id"]].append(i)
    last = _last_receipts(db)
    promises = _open_promises(list_collections(db))

    rows, all_invs = [], []
    locked_amt, at_risk_amt = Decimal("0.00"), Decimal("0.00")
    for c in clients:
        invs = by_client[c.id]
        all_invs.extend(invs)
        lock = cl_svc.lock_state(invs, client_id=c.id, as_of=as_of, grace_days=grace,
                                 override_until=c.lock_override_until)
        if lock["lock_status"] == "locked":
            locked_amt += Decimal(str(lock["outstanding"]))
        elif lock["lock_status"] == "at_risk":
            at_risk_amt += Decimal(str(lock["overdue_amount"]))
        rows.append({
            "client_id": c.id, "client_name": c.name or "",
            "credit_days": int(c.credit_days if c.credit_days is not None else M.DEFAULTS.credit_days),
            "outstanding": lock["outstanding"], "buckets": cl_svc.ageing(invs),
            "oldest_due_date": lock["oldest_due"], "max_days_past_due": lock["max_days_past_due"],
            "lock_status": lock["lock_status"], "locks_on": lock["locks_on"],
            "locked_since": lock["locked_since"], "last_receipt_date": jsonable(last.get(c.id)),
            "promise": promises.get(c.id),
        })
    rows.sort(key=lambda r: (-r["outstanding"], r["client_id"]))
    buckets = cl_svc.ageing(all_invs)
    return {
        "as_of": as_of.isoformat(),
        "grace_days": grace,
        "totals": {
            "outstanding": _sum(r["outstanding"] for r in rows),
            "overdue": _sum(v for k, v in buckets.items() if k != "not_due"),
            "at_risk": float(at_risk_amt),
            "locked": float(locked_amt),
            "buckets": buckets,
        },
        "clients": rows,
    }


# ---------------------------------------------------------------- collections


def _collection_status(stored: str, promise_date: date | None, promise_amount, received: Decimal,
                       as_of: date) -> str:
    """Stored ``kept``/``broken`` wins; an ``open`` promise whose date has passed is ``kept``
    when receipts from the entry date to the promise date cover it, else ``broken``."""
    stored = (stored or "open").lower()
    if stored in ("kept", "broken") or promise_date is None or promise_date >= as_of:
        return stored if stored in ("open", "kept", "broken") else "open"
    target = Decimal(str(promise_amount)) if promise_amount is not None else Decimal("0.01")
    return "kept" if received >= target else "broken"


def list_collections(db: Session, *, collection_id: str | None = None) -> list[dict]:
    """Collection diary entries (contract ``Collection``) in date order."""
    col, cl, rcp = T("collections"), T("clients"), T("receipts")
    q = select(col, cl.c.name.label("client_name")).join(cl, cl.c.id == col.c.client_id, isouter=True)
    if collection_id is not None:
        q = q.where(col.c.id == collection_id)
    rows = db.execute(q.order_by(col.c.date, col.c.id)).all()
    as_of = today()
    receipts: dict[str, list[tuple[date, Decimal]]] = defaultdict(list)
    if any(r._mapping["promise_date"] for r in rows):
        for cid, d, amt in db.execute(select(rcp.c.client_id, rcp.c.date, rcp.c.amount)):
            receipts[cid].append((d, Decimal(str(amt or 0))))
    out = []
    for r in rows:
        m = r._mapping
        pd = m["promise_date"]
        got = sum((a for d, a in receipts.get(m["client_id"], []) if pd and m["date"] <= d <= pd), Decimal("0"))
        out.append({
            "id": m["id"], "date": jsonable(m["date"]), "client_id": m["client_id"],
            "client_name": m["client_name"] or "", "invoice_ids": list(m["invoice_ids"] or []),
            "mode": m["mode"] if m["mode"] in COLLECTION_MODES else "call", "contact": m["contact"] or "",
            "note": m["note"] or "", "promise_date": jsonable(pd),
            "promise_amount": money(m["promise_amount"]) if m["promise_amount"] is not None else None,
            "status": _collection_status(m["status"], pd, m["promise_amount"], got, as_of),
            "next_follow_up": jsonable(m["next_follow_up"]), "by": m["by"] or "",
            "is_demo": bool(m["is_demo"]),
        })
    return out


def create_collection(db: Session, body: dict, role: str) -> dict:
    """Log a follow-up / promise. 400 unknown client, bad mode, or invoices of another client."""
    col, inv = T("collections"), T("invoices")
    client_id = (body["client_id"] or "").strip().upper()
    client = cl_svc.get_client_row(db, client_id)
    if client is None:
        raise bad_request(f"client_id: unknown client {client_id}")
    mode = (body["mode"] or "").strip().lower()
    if mode not in COLLECTION_MODES:
        raise bad_request(f"mode: must be one of {', '.join(COLLECTION_MODES)}")
    note = (body["note"] or "").strip()
    if not note:
        raise bad_request("note: a note is required")
    invoice_ids = [i.strip().upper() for i in body.get("invoice_ids") or [] if i and i.strip()]
    if invoice_ids:
        found = {i: c for i, c in db.execute(select(inv.c.id, inv.c.client_id).where(inv.c.id.in_(invoice_ids)))}
        bad = [i for i in invoice_ids if found.get(i) != client_id]
        if bad:
            raise bad_request(f"invoice_ids: {', '.join(bad)} are not invoices of {client_id}")
    amount = body.get("promise_amount")
    if amount is not None and amount < 0:
        raise bad_request("promise_amount must not be negative")
    promise_date = body.get("promise_date")
    if amount is not None and promise_date is None:
        raise bad_request("promise_date: required when a promise amount is given")
    if promise_date is not None and promise_date < body["date"]:
        raise bad_request("promise_date must not be before the entry date")

    col_id = next_id(db, "collections", "COL", 4)
    values: dict[str, Any] = {
        "id": col_id, "date": body["date"], "client_id": client_id, "invoice_ids": invoice_ids,
        "mode": mode, "contact": (body.get("contact") or client["contact"] or "").strip(), "note": note,
        "promise_date": promise_date,
        "promise_amount": float(M.money(amount)) if amount is not None else None,
        "status": "open", "next_follow_up": body.get("next_follow_up") or promise_date,
        "by": role.capitalize(), "is_demo": False,
    }
    db.execute(col.insert().values({k: v for k, v in values.items() if k in col.c}))
    audit(db, role=role, action="collection_create", entity="collection", entity_id=col_id, after=values)
    db.commit()
    found = list_collections(db, collection_id=col_id)
    return found[0] if found else {}
