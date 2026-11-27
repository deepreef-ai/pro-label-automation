"""Move a job's status forward as its work happens (planned -> ... -> invoiced).

Before this only starting a press run changed a job's status, so a job that was checked, dispatched
and invoiced still showed ``printing`` on the dashboard, Floor Board and run picker.
A status never moves backwards and ``hold`` / ``closed`` are left alone (owner decisions).
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import audit
from app.deps import T

ORDER = ("planned", "design", "printing", "qc", "dispatch", "invoiced", "closed")
KEEP = ("hold", "closed")


def advance(db: Session, job_card: str, to: str, *, role: str, reason: str) -> None:
    """Set ``to`` if it is later than the job's current status (audited as ``job_status``)."""
    jobs = T("jobs")
    current = db.execute(select(jobs.c.status).where(jobs.c.job_card == job_card)).scalar()
    if current is None or current in KEEP or current not in ORDER:
        return
    if ORDER.index(to) <= ORDER.index(current):
        return
    db.execute(jobs.update().where(jobs.c.job_card == job_card).values(status=to))
    audit(db, role=role, action="job_status", entity="job", entity_id=job_card,
          before={"status": current}, after={"status": to}, reason=reason)
