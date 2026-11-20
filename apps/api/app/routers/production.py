"""Production endpoints (SPEC 3, issue #16): production log, start/end a run, press setup,
OEE, morning report and the live counter (simulated SSE).

Maths (wastage, flags, hour rate, crew cost, OEE, press-only printed totals) is in
``core.rules.production`` via ``app.services.production``.
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import date, datetime, timezone
from typing import Literal

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.audit import audit, next_id
from app.deps import DB, Role, T, allow, bad_request, conflict, not_found
from app.serialize import now
from app.services import jobs as job_svc
from app.services import production as svc
from core.rules.store import JOB_CARD_RE

router = APIRouter()

READERS = ("production", "ppic", "qc")
NOT_READY = ("invoiced", "closed", "hold")  # job statuses that cannot go on a press
COUNTER_INTERVAL_S = 2.0
COUNTER_MAX_TICKS = 1800  # ~1 h per connection; the board reconnects


class StopIn(BaseModel):
    reason: str = Field(min_length=1)
    minutes: int = Field(ge=0)


class RunStart(BaseModel):
    model_config = ConfigDict(extra="ignore")

    job_card: str = Field(min_length=1)
    machine_id: str = Field(min_length=1)
    operator: str = Field(min_length=1)
    shift: Literal["day", "night"]


class RunEnd(BaseModel):
    model_config = ConfigDict(extra="ignore")

    printed_qty: int = Field(ge=0)
    used_m: float = Field(ge=0)
    stops: list[StopIn] = Field(default_factory=list)
    end: datetime | None = None


class PressUnitIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    unit: int = Field(ge=1)
    colour: str = Field(min_length=1)
    anilox_lpi: int = Field(ge=0)
    anilox_bcm: float = Field(ge=0)
    plate_id: str | None = None
    ink_item_id: str | None = None


class PressSetupInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    job_card: str = Field(min_length=1)
    machine_id: str = Field(min_length=1)
    web_width_mm: int = Field(gt=0)
    die_id: str | None = None
    units: list[PressUnitIn]
    speed_target_mpm: int | None = Field(default=None, ge=0)
    notes: str | None = None


def _job_card(raw: str) -> str:
    jc = raw.strip().upper()
    if not JOB_CARD_RE.match(jc):
        raise bad_request(f"invalid job card '{raw}' (expected JC-####)")
    return jc


def _machine(db, machine_id: str):
    mc = T("machines")
    m = db.execute(select(mc.c.id, mc.c.name, mc.c.type).where(mc.c.id == machine_id)).first()
    if m is None:
        raise bad_request(f"unknown machine {machine_id}")
    return m


# ---------------------------------------------------------------- runs

@router.get("/production/runs", dependencies=[allow(*READERS)])
def get_runs(db: DB, status: str | None = None, machine_id: str | None = None,
             job_card: str | None = None) -> list[dict]:
    if status is not None and status not in svc.RUN_STATUSES:
        raise bad_request(f"status must be one of {', '.join(svc.RUN_STATUSES)}")
    jc = _job_card(job_card) if job_card else None
    return svc.list_runs(db, status=status or None, machine_id=(machine_id or "").strip() or None, job_card=jc)


@router.post("/production/runs/start", status_code=201, dependencies=[allow("production")])
def post_run_start(body: RunStart, db: DB, role: Role) -> dict:
    jc = _job_card(body.job_card)
    job = job_svc.get_job(db, jc)
    if job is None:
        raise bad_request(f"unknown job card {jc}")
    machine = _machine(db, body.machine_id.strip())
    if job["status"] in NOT_READY:
        raise conflict(f"job {jc} is {job['status']}; it cannot start on a machine")
    rn = T("runs")
    busy = db.execute(select(rn.c.id, rn.c.job_card, rn.c.is_demo)
                      .where(rn.c.machine_id == machine.id, rn.c.end.is_(None))).all()
    # The seeded "live" runs (is_demo) are simulated counters for the floor board; a run started
    # in the app (or the same job already running here) blocks the machine.
    clash = next((r for r in busy if not r.is_demo or r.job_card == jc), None)
    if clash is not None:
        raise conflict(f"{machine.name} already has a running run {clash.id} ({clash.job_card}); end it first")

    run_id = next_id(db, "runs", "RUN", 5)
    row = {"id": run_id, "job_card": jc, "machine_id": machine.id, "shift": body.shift,
           "operator": body.operator.strip(), "start": svc.plant_now(), "end": None, "hours": None,
           "printed_qty": 0, "used_m": None, "stops": [], "is_demo": False}
    db.execute(rn.insert().values(row))
    if job["status"] in ("planned", "design"):
        jobs = T("jobs")
        db.execute(jobs.update().where(jobs.c.job_card == jc).values(status="printing"))
        audit(db, role=role, action="job_status", entity="job", entity_id=jc,
              before={"status": job["status"]}, after={"status": "printing"}, reason=f"run {run_id} started")
    audit(db, role=role, action="run_start", entity="run", entity_id=run_id, after=row)
    db.commit()
    return svc.get_run(db, run_id) or {}


@router.post("/production/runs/{run_id}/end", dependencies=[allow("production")])
def post_run_end(run_id: str, body: RunEnd, db: DB, role: Role) -> dict:
    rid = run_id.strip().upper()
    r = svc.run_row(db, rid)
    if r is None:
        raise not_found("run", rid)
    if r.end is not None:
        raise conflict(f"run {rid} already ended at {r.end.isoformat()}")
    end = svc.to_plant(body.end) if body.end is not None else svc.plant_now()
    if end <= r.start:
        raise bad_request(f"end {end.isoformat()} must be after start {r.start.isoformat()}")
    hours = round((end - r.start).total_seconds() / 3600, 2)
    before = svc.get_run(db, rid)
    values = {"end": end, "hours": hours, "printed_qty": body.printed_qty, "used_m": body.used_m,
              "stops": [s.model_dump() for s in body.stops]}
    rn = T("runs")
    db.execute(rn.update().where(rn.c.id == rid).values(values))
    after = svc.get_run(db, rid) or {}
    flags = [f for f in ("wastage_flag", "overprod_flag") if after.get(f)]
    audit(db, role=role, action="run_end", entity="run", entity_id=rid, before=before, after=after,
          reason=", ".join(flags) or None)
    db.commit()
    return svc.get_run(db, rid) or {}


# ---------------------------------------------------------------- press setup

@router.get("/production/press-setup/{job_card}", dependencies=[allow(*READERS, "design")])
def get_press_setup(job_card: str, db: DB) -> dict:
    jc = _job_card(job_card)
    job = job_svc.get_job(db, jc)
    if job is None:
        raise not_found("job", jc)
    return svc.press_setup(db, job)


@router.post("/production/press-setup", status_code=201, dependencies=[allow("production", "design")])
def post_press_setup(body: PressSetupInput, db: DB, role: Role) -> dict:
    jc = _job_card(body.job_card)
    job = job_svc.get_job(db, jc)
    if job is None:
        raise bad_request(f"unknown job card {jc}")
    machine = _machine(db, body.machine_id.strip())
    if body.die_id:
        dies = T("dies")
        if db.execute(select(dies.c.id).where(dies.c.id == body.die_id)).first() is None:
            raise bad_request(f"unknown die {body.die_id}")
    numbers = [u.unit for u in body.units]
    if len(numbers) != len(set(numbers)):
        raise bad_request("unit numbers must be unique")
    units = [u.model_dump() for u in sorted(body.units, key=lambda u: u.unit)]
    est = svc.ink_estimate_kg(db, units, svc.job_area_m2(job, body.web_width_mm))
    ps = T("press_setup")
    key = (ps.c.job_card == jc) & (ps.c.machine_id == machine.id)
    old = db.execute(select(ps).where(key)).first()
    values = {"web_width_mm": body.web_width_mm, "die_id": body.die_id or None, "units": units,
              "speed_target_mpm": body.speed_target_mpm if body.speed_target_mpm is not None
              else (int(old.speed_target_mpm or 0) if old is not None else 0),
              "est_ink_kg": est, "notes": (body.notes or "").strip(), "updated_by": role,
              "updated_at": now().astimezone(timezone.utc).replace(tzinfo=None)}
    if old is None:
        db.execute(ps.insert().values({"job_card": jc, "machine_id": machine.id, "is_demo": False, **values}))
    else:
        db.execute(ps.update().where(key).values(values))
    audit(db, role=role, action="press_setup_save", entity="press_setup", entity_id=f"{jc}/{machine.id}",
          before={k: getattr(old, k) for k in values if k != "updated_at"} if old is not None else None,
          after={"job_card": jc, "machine_id": machine.id, **{k: v for k, v in values.items() if k != "updated_at"}})
    db.commit()
    return svc.press_setup(db, job, machine_id=machine.id)


# ---------------------------------------------------------------- OEE and morning report

@router.get("/production/oee", dependencies=[allow(*READERS)])
def get_oee(db: DB, month: str | None = None) -> dict:
    try:
        return svc.oee(db, month)
    except ValueError as exc:
        raise bad_request(str(exc)) from exc


@router.get("/production/morning-report", dependencies=[allow(*READERS)])
def get_morning_report(db: DB, date: date | None = None) -> dict:
    return svc.morning_report(db, date)


# ---------------------------------------------------------------- live counter (SSE)

async def _ticks(seed: dict) -> AsyncIterator[str]:
    i = 0
    while True:
        tick = svc.counter_tick(seed, i, COUNTER_INTERVAL_S)
        yield f"data: {json.dumps(tick)}\n\n"
        if tick["status"] == "ended" or i >= COUNTER_MAX_TICKS:
            return
        i += 1
        await asyncio.sleep(COUNTER_INTERVAL_S)


@router.get("/production/counter/stream", dependencies=[allow(*READERS)])
def get_counter_stream(db: DB, run_id: str | None = None) -> StreamingResponse:
    rid = (run_id or "").strip().upper()
    if not rid:
        raise bad_request("run_id is required")
    r = svc.run_row(db, rid)
    if r is None:
        raise bad_request(f"unknown run {rid}")
    ps = T("press_setup")
    speed = db.execute(select(ps.c.speed_target_mpm)
                       .where(ps.c.job_card == r.job_card, ps.c.machine_id == r.machine_id)).scalar()
    seed = svc.counter_seed(r, speed)
    return StreamingResponse(_ticks(seed), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
