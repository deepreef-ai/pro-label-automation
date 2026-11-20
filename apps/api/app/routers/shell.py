"""Shell endpoints: health, settings, feedback (SPEC 3 "Shell"). Search lives in masters.py."""
from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.audit import audit, next_id
from app.deps import ALL, DB, Role, T, allow
from app.serialize import now, row_dict

router = APIRouter()

VERSION = "0.1.0"
SETTINGS_FIELDS = (
    "wastage_tol", "overprod_tol", "material_tol", "ink_tol", "slit_tol", "grn_rate_tol", "grace_days",
    "msme_days", "gst_rate", "planning_extra", "admin_pct", "ai_mode", "stock_from", "fy_start",
    "company_name", "updated_at", "updated_by",
)
FRACTIONS = ("wastage_tol", "overprod_tol", "material_tol", "ink_tol", "slit_tol", "grn_rate_tol",
             "gst_rate", "planning_extra", "admin_pct")


# ---------------------------------------------------------------- health

@router.get("/health", dependencies=[allow(*ALL)])
def health(db: DB) -> dict:
    db_ok, demo, ai_mode = "ok", False, "cloud"
    try:
        db.execute(text("SELECT 1"))
        s = load_settings(db)
        ai_mode = s.get("ai_mode") or "cloud"
        jobs = T("jobs")
        demo = db.execute(select(jobs.c.job_card).where(jobs.c.is_demo.is_(True)).limit(1)).first() is not None
    except Exception:  # noqa: BLE001 - health must answer even when the DB is broken
        db_ok = "down"
    return {
        "status": "ok" if db_ok == "ok" else "degraded",
        "version": VERSION,
        "time": now().isoformat(),
        "db": db_ok,
        "ai_mode": ai_mode if ai_mode in ("cloud", "local", "off") else "cloud",
        "demo": demo,
    }


# ---------------------------------------------------------------- settings

def _settings_row(db: Session):
    tbl = T("settings")
    return tbl, db.execute(select(tbl).order_by(tbl.c.id).limit(1)).first()


def load_settings(db: Session) -> dict:
    """The single settings row as a contract dict (also used by other routers for tolerances)."""
    _tbl, row = _settings_row(db)
    if row is None:
        from core.rules.settings import DEFAULTS

        return {k: getattr(DEFAULTS, k) for k in SETTINGS_FIELDS if hasattr(DEFAULTS, k)}
    d = row_dict(row)
    out = {k: d.get(k) for k in SETTINGS_FIELDS}
    for k in FRACTIONS:
        if out.get(k) is not None:
            out[k] = round(float(out[k]), 4)
    return out


class SettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    wastage_tol: float | None = Field(None, ge=0, le=1)
    overprod_tol: float | None = Field(None, ge=0, le=1)
    material_tol: float | None = Field(None, ge=0, le=1)
    ink_tol: float | None = Field(None, ge=0, le=1)
    slit_tol: float | None = Field(None, ge=0, le=1)
    grn_rate_tol: float | None = Field(None, ge=0, le=1)
    grace_days: int | None = Field(None, ge=0, le=365)
    msme_days: int | None = Field(None, ge=0, le=365)
    gst_rate: float | None = Field(None, ge=0, le=1)
    planning_extra: float | None = Field(None, ge=0, le=1)
    admin_pct: float | None = Field(None, ge=0, le=1)
    ai_mode: Literal["cloud", "local", "off"] | None = None
    stock_from: date | None = None
    fy_start: date | None = None
    company_name: str | None = Field(None, min_length=1)


@router.get("/settings", dependencies=[allow(*ALL)])
def get_settings(db: DB) -> dict:
    return load_settings(db)


@router.put("/settings", dependencies=[allow("owner")])
def put_settings(body: SettingsUpdate, db: DB, role: Role) -> dict:
    changes = body.model_dump(exclude_none=True)
    tbl, row = _settings_row(db)
    before_all = load_settings(db)
    if not changes:
        return before_all
    changes = {k: v for k, v in changes.items() if k in tbl.c}
    stamp = {"updated_by": role} | ({"updated_at": now()} if "updated_at" in tbl.c else {})
    if row is None:
        db.execute(tbl.insert().values({"id": 1, **changes, **stamp}))
    else:
        db.execute(tbl.update().where(tbl.c.id == row._mapping["id"]).values({**changes, **stamp}))
    audit(db, role=role, action="settings_update", entity="settings", entity_id="1",
          before={k: before_all.get(k) for k in changes}, after=changes)
    db.commit()
    return load_settings(db)


# ---------------------------------------------------------------- feedback

class FeedbackCreate(BaseModel):
    screen: str = Field(min_length=1)
    message: str = Field(min_length=1)
    rating: int | None = Field(None, ge=1, le=5)


FEEDBACK_FIELDS = ("id", "created_at", "role", "screen", "message", "rating", "status")


@router.post("/feedback", status_code=201, dependencies=[allow(*ALL)])
def create_feedback(body: FeedbackCreate, db: DB, role: Role) -> dict:
    tbl = T("feedback")
    fb_id = next_id(db, "feedback", "FB", 4)
    row = {"id": fb_id, "created_at": now(), "role": role, "screen": body.screen.strip(),
           "message": body.message.strip(), "rating": body.rating, "status": "new"}
    db.execute(tbl.insert().values({k: v for k, v in row.items() if k in tbl.c}))
    audit(db, role=role, action="feedback_create", entity="feedback", entity_id=fb_id, after=row)
    db.commit()
    return _feedback(db.execute(select(tbl).where(tbl.c.id == fb_id)).one())


@router.get("/feedback", dependencies=[allow(*ALL)])
def list_feedback(db: DB) -> list[dict]:
    tbl = T("feedback")
    rows = db.execute(select(tbl).order_by(tbl.c.created_at.desc(), tbl.c.id.desc())).all()
    return [_feedback(r) for r in rows]


def _feedback(row) -> dict:
    d = row_dict(row)
    return {k: d.get(k) for k in FEEDBACK_FIELDS}
