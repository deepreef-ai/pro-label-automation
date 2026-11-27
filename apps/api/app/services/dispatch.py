"""Dispatch register and delivery challans (SPEC 2 bullet 7, SPEC 3 "Dispatch", issue #16).

The guard (cumulative dispatched <= QC approved, else 409) is ``core.rules.quality.check_dispatch``;
QC approved comes from ``services.jobs`` (``approved_total`` over the job's QC rows).
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import audit, next_id
from app.deps import T, bad_request, conflict
from app.serialize import jsonable, money
from app.services import jobs as jobs_svc
from app.services.clients import client_lock
from core.rules import quality as Q
from core.rules.errors import RuleError


def _approved_by_job(db: Session, cards: set[str] | None) -> dict[str, int]:
    qc = T("qc")
    stmt = select(qc.c.job_card, qc.c.approved, qc.c.decision)
    if cards is not None:
        stmt = stmt.where(qc.c.job_card.in_(cards))
    rows: dict[str, list[dict]] = defaultdict(list)
    for jc, approved, decision in db.execute(stmt):
        rows[jc].append({"approved_qty": approved, "decision": decision})
    return {jc: Q.approved_total(r) for jc, r in rows.items()}


def list_dispatches(db: Session, *, job_card: str | None = None, dispatch_id: str | None = None) -> list[dict]:
    """Contract ``Dispatch`` dicts in date order, with the running balance against QC approved."""
    d, jobs, clients, inv = T("dispatches"), T("jobs"), T("clients"), T("invoices")
    stmt = (
        select(*d.c, jobs.c.client_id, clients.c.name.label("client_name"),
               inv.c.id.label("invoice_id"))
        .select_from(d)
        .join(jobs, jobs.c.job_card == d.c.job_card, isouter=True)
        .join(clients, clients.c.id == jobs.c.client_id, isouter=True)
        .join(inv, inv.c.dispatch_id == d.c.id, isouter=True)
    )
    if dispatch_id:  # the running balance needs the job's earlier challans too
        jc = db.execute(select(d.c.job_card).where(d.c.id == dispatch_id)).scalar()
        if jc is None:
            return []
        job_card = jc
    if job_card:
        stmt = stmt.where(d.c.job_card == job_card)
    rows = db.execute(stmt.order_by(d.c.date, d.c.id)).all()
    approved = _approved_by_job(db, {r.job_card for r in rows} if job_card else None)
    before: dict[str, int] = defaultdict(int)
    out = []
    for r in rows:
        qty = int(r.qty or 0)
        appr = approved.get(r.job_card, 0)
        prev = before[r.job_card]
        before[r.job_card] = prev + qty
        out.append({
            "id": r.id,
            "date": jsonable(r.date),
            "job_card": r.job_card,
            "client_id": r.client_id or "",
            "client_name": r.client_name or "",
            "qty": qty,
            "boxes": int(r.boxes or 0),
            "vehicle_no": r.vehicle_no or "",
            "transporter": r.transporter or "",
            "freight": money(r.freight),
            "lr_no": r.lr_no or "",
            "qc_approved": appr,
            "dispatched_before": prev,
            "balance_after": appr - prev - qty,
            "status": "invoiced" if r.invoice_id else "dispatched",
            "invoice_id": r.invoice_id,
            "is_demo": bool(r.is_demo),
        })
    if dispatch_id:
        out = [x for x in out if x["id"] == dispatch_id]
    return out


def get_dispatch(db: Session, dispatch_id: str) -> dict | None:
    found = list_dispatches(db, dispatch_id=dispatch_id)
    return found[0] if found else None


def create_dispatch(db: Session, body: dict, role: str) -> dict:
    """Save one challan. 400 unknown job, 409 above QC approved or client LOCKED."""
    d = T("dispatches")
    jc = body["job_card"].strip().upper()
    job = jobs_svc.get_job(db, jc)
    if job is None:
        raise bad_request(f"unknown job card {jc}")
    qty = body["qty"]
    if qty <= 0:
        raise bad_request("qty must be positive")
    approved, already = int(job["qc_approved"]), int(job["dispatched_qty"])
    try:
        Q.check_dispatch(approved, already, qty)
    except RuleError as exc:
        raise conflict(f"{jc}: {exc}") from exc

    lock = client_lock(db, job["client_id"])
    if lock.get("lock_status") == "locked":
        reason = lock.get("reason") or "unpaid invoice past due + grace"
        raise conflict(f"client {job['client_id']} is LOCKED ({reason}); only the owner can release the lock")

    dc_id = next_id(db, "dispatches", "DC", 4)
    row = {
        "id": dc_id, "date": body["date"], "job_card": jc, "qty": qty, "boxes": body.get("boxes") or 0,
        "vehicle_no": body["vehicle_no"].strip(), "transporter": body["transporter"].strip(),
        "lr_no": (body.get("lr_no") or "").strip(), "freight": round(float(body["freight"]), 2),
        "is_demo": False,
    }
    db.execute(d.insert().values({k: v for k, v in row.items() if k in d.c}))
    audit(db, role=role, action="dispatch_create", entity="dispatch", entity_id=dc_id,
          after={**row, "qc_approved": approved, "dispatched_before": already})
    from app.services import job_status

    job_status.advance(db, jc, "dispatch", role=role, reason=f"challan {dc_id}")
    db.commit()
    return get_dispatch(db, dc_id) or {}


def challan_data(db: Session, dispatch_id: str) -> dict[str, Any] | None:
    """The challan dict plus the job's product (for the PDF)."""
    dc = get_dispatch(db, dispatch_id)
    if dc is None:
        return None
    jobs = T("jobs")
    job = db.execute(select(jobs.c.product, jobs.c.po_no, jobs.c.label_size)
                     .where(jobs.c.job_card == dc["job_card"])).first()
    return {**dc, "product": (job.product if job else "") or "", "po_no": (job.po_no if job else "") or "",
            "label_size": (job.label_size if job else "") or ""}
