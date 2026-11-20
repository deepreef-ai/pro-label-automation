"""Owner screens: dashboard summary, alerts, Job 360, floor board (SPEC 3). Issue #17 (A3)."""
from __future__ import annotations

from fastapi import APIRouter

from app.deps import ALL, DB, Role, allow, bad_request, not_found
from app.services import dashboard as svc
from app.services.job360 import job_360
from core.rules.store import JOB_CARD_RE

router = APIRouter()


@router.get("/dashboard/summary", dependencies=[allow("owner", "accounts")])
def get_dashboard_summary(db: DB, period: str = "month") -> dict:
    p = (period or "month").strip().lower()
    if p not in svc.PERIODS:
        raise bad_request(f"period must be one of {', '.join(svc.PERIODS)}")
    return svc.summary(db, p)


@router.get("/alerts", dependencies=[allow(*ALL)])
def get_alerts(db: DB, role: Role) -> dict:
    return svc.alerts(db, role)


@router.get("/jobs/{job_card}/360", dependencies=[allow(*ALL)])
def get_job_360(job_card: str, db: DB) -> dict:
    jc = job_card.strip().upper()
    if not JOB_CARD_RE.match(jc):
        raise bad_request(f"invalid job card '{job_card}' (expected JC-####)")
    out = job_360(db, jc)
    if out is None:
        raise not_found("job", jc)
    return out


@router.get("/floor/board", dependencies=[allow(*ALL)])
def get_floor_board(db: DB) -> dict:
    return svc.floor_board(db)
