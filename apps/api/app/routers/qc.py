"""qc endpoints (SPEC 3). Issue #16 (A2): QC log and inspection entry."""
from __future__ import annotations

import datetime as dt
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from app.deps import DB, Role, allow, bad_request
from app.services import qc as svc
from core.rules.store import JOB_CARD_RE

router = APIRouter()


class Defect(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: str = Field(min_length=1)
    qty: int = Field(ge=0)


class QcCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    date: dt.date
    job_card: str = Field(min_length=1)
    run_id: str | None = None
    checked: int = Field(ge=0)
    approved: int = Field(ge=0)
    rejected: int = Field(ge=0)
    decision: Literal["Approved", "Approved with Deviation", "Hold", "Rework", "Rejected"]
    defects: list[Defect] = Field(default_factory=list)
    inspector: str = Field(min_length=1)
    notes: str = ""


@router.get("/qc", dependencies=[allow("qc", "production", "dispatch", "ppic")])
def get_qc(db: DB, job_card: str | None = None) -> list[dict]:
    jc = (job_card or "").strip().upper() or None
    if jc is not None and not JOB_CARD_RE.match(jc):
        raise bad_request(f"invalid job card '{job_card}' (expected JC-####)")
    return svc.list_qc(db, jc)


@router.post("/qc", status_code=201, dependencies=[allow("qc")])
def post_qc(body: QcCreate, db: DB, role: Role) -> dict:
    return svc.create_qc(db, body.model_dump(), role)
