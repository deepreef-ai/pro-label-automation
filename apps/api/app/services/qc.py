"""QC log and inspection entry (SPEC 2 bullet 6, SPEC 3 "QC", issue #16).

The guards (approved + rejected == checked, cumulative checked <= printed, which decisions
count as approved) live in ``core.rules.quality``; printed is the press-only total from
``core.rules.production`` (read through ``services.jobs.get_job``).
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit import audit, next_id
from app.deps import T, bad_request
from app.serialize import jsonable
from app.services import jobs as jobs_svc
from core.rules import quality as Q
from core.rules.errors import RuleError, ratio

DECISIONS = ("Approved", "Approved with Deviation", "Hold", "Rework", "Rejected")


def _select():
    qc, jobs, clients = T("qc"), T("jobs"), T("clients")
    return (
        select(*qc.c, clients.c.name.label("client_name"))
        .select_from(qc)
        .join(jobs, jobs.c.job_card == qc.c.job_card, isouter=True)
        .join(clients, clients.c.id == jobs.c.client_id, isouter=True)
    )


def _row(r: Any) -> dict:
    checked = int(r.checked or 0)
    rejected = int(r.rejected or 0)
    return {
        "id": r.id,
        "date": jsonable(r.date),
        "job_card": r.job_card,
        "client_name": r.client_name or "",
        "run_id": r.run_id,
        "checked": checked,
        "approved": int(r.approved or 0),
        "rejected": rejected,
        "rejection_pct": float(ratio(rejected, checked)) if checked else 0.0,
        "decision": r.decision,
        "counts_as_approved": Q.counts_as_approved(r.decision),
        "defects": [{"type": str(d.get("type") or ""), "qty": int(d.get("qty") or 0)}
                    for d in (r.defects or []) if isinstance(d, dict)],
        "inspector": r.inspector or "",
        "notes": r.notes or "",
        "is_demo": bool(r.is_demo),
    }


def list_qc(db: Session, job_card: str | None = None) -> list[dict]:
    qc = T("qc")
    stmt = _select()
    if job_card:
        stmt = stmt.where(qc.c.job_card == job_card)
    return [_row(r) for r in db.execute(stmt.order_by(qc.c.date, qc.c.id))]


def get_qc(db: Session, qc_id: str) -> dict | None:
    r = db.execute(_select().where(T("qc").c.id == qc_id)).first()
    return _row(r) if r is not None else None


def create_qc(db: Session, body: dict, role: str) -> dict:
    """Validate and save one inspection. Raises HTTP 400 on any broken rule."""
    qc, runs = T("qc"), T("runs")
    jc = body["job_card"].strip().upper()
    if body["decision"] not in DECISIONS:  # approved_total uses a blocklist: never store an unknown decision
        raise bad_request(f"decision must be one of {', '.join(DECISIONS)}")
    job = jobs_svc.get_job(db, jc)
    if job is None:
        raise bad_request(f"unknown job card {jc}")
    run_id = (body.get("run_id") or "").strip() or None
    if run_id:
        run_job = db.execute(select(runs.c.job_card).where(runs.c.id == run_id)).scalar()
        if run_job is None:
            raise bad_request(f"unknown run {run_id}")
        if run_job != jc:
            raise bad_request(f"run {run_id} belongs to {run_job}, not {jc}")

    printed = int(job["printed_qty"])
    already = int(db.execute(select(func.coalesce(func.sum(qc.c.checked), 0))
                             .where(qc.c.job_card == jc)).scalar_one())
    checked, approved, rejected = body["checked"], body["approved"], body["rejected"]
    try:
        Q.qc_validate(printed, checked, approved, rejected)
        Q.qc_validate(printed, already + checked, already + approved, rejected)
    except RuleError as exc:
        msg = str(exc)
        if already and approved + rejected == checked and checked <= printed:
            msg = (f"checked ({checked}) plus already checked ({already}) "
                   f"cannot exceed printed ({printed})")
        raise bad_request(msg) from exc

    defects = []
    for d in body.get("defects") or []:
        if d["qty"] < 0:
            raise bad_request("defect qty must not be negative")
        defects.append({"type": d["type"].strip(), "qty": d["qty"]})

    qc_id = next_id(db, "qc", "QC", 5)
    row = {
        "id": qc_id, "date": body["date"], "job_card": jc, "run_id": run_id, "checked": checked,
        "approved": approved, "rejected": rejected, "decision": body["decision"], "defects": defects,
        "inspector": body["inspector"].strip(), "notes": (body.get("notes") or "").strip(), "is_demo": False,
    }
    db.execute(qc.insert().values({k: v for k, v in row.items() if k in qc.c}))
    audit(db, role=role, action="qc_create", entity="qc", entity_id=qc_id, after=row)
    db.commit()
    return get_qc(db, qc_id) or {}
