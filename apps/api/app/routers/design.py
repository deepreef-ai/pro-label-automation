"""Design endpoints (SPEC 3 "Design"): design register, design record per job, Plate Store, Die Store.

Rules live in :mod:`app.services.design`.
"""
from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from app.deps import DB, Role, allow
from app.services import design as svc

router = APIRouter()

Stage = Literal["artwork", "proof_sent", "approved", "plates_ordered", "plates_ready", "done"]
READERS = ("design", "ppic", "production")


class DesignUnit(BaseModel):
    unit: int
    colour: str
    anilox_lpi: int | None = None
    plate_id: str | None = None


class DesignUpdate(BaseModel):
    """Any subset of editable Design fields (openapi ``DesignUpdate``); only sent keys change."""

    model_config = ConfigDict(extra="ignore")

    stage: Stage | None = None
    designer: str | None = None
    artwork_version: int | None = None
    proof_sent_on: date | None = None
    approved_on: date | None = None
    approved_by: str | None = None
    die_id: str | None = None
    units: list[DesignUnit] | None = None
    route: list[str] | None = None
    notes: str | None = None


@router.get("/design", dependencies=[allow(*READERS)])
def get_design_register(db: DB, stage: Stage | None = None) -> list[dict]:
    return svc.list_design(db, stage)


@router.get("/design/{job_card}", dependencies=[allow(*READERS)])
def get_design(job_card: str, db: DB) -> dict:
    return svc.get_design(db, job_card)


@router.put("/design/{job_card}", dependencies=[allow("design")])
def put_design(job_card: str, body: DesignUpdate, db: DB, role: Role) -> dict:
    return svc.update_design(db, job_card, body.model_dump(exclude_unset=True), role)


@router.get("/plates", dependencies=[allow(*READERS, "store")])
def get_plates(db: DB) -> list[dict]:
    return svc.list_plates(db)


@router.get("/dies", dependencies=[allow(*READERS, "store")])
def get_dies(db: DB) -> list[dict]:
    return svc.list_dies(db)
