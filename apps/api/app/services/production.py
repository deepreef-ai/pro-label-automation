"""Production log, press setup, OEE, morning report and the live counter (SPEC 2 and 3, issue #16).

All metres, wastage, tolerance, hour-rate, crew-cost and OEE maths goes through
``core.rules.production``; this module gathers rows and shapes contract JSON (``Run``,
``PressSetup``, ``Oee``, ``MorningReport``, ``CounterTick`` in contract/openapi.yaml).

Datetimes in ``runs`` are stored naive in plant time (IST), like the demo data.
"""
from __future__ import annotations

import math
from calendar import monthrange
from collections import defaultdict
from collections.abc import Iterable
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.deps import T, today
from app.serialize import IST, jsonable, now
from app.services import jobs as job_svc
from core.rules import production as P
from core.rules.errors import RuleError, dec

SHIFTS = ("day", "night")
RUN_STATUSES = ("running", "ended")
SHIFT_HOURS = 8  # one planned shift per machine per day (OEE planned time, morning-report idle time)
# Ink estimate defaults (overridable from settings.extra, where the client's admin cells land).
BCM_TO_CM3_PER_M2 = Decimal("1.55")  # 1 BCM/sq inch of anilox volume = 1.55 cm3 per sq m
INK_DEFAULTS = {"anilox_transfer": Decimal("0.30"), "ink_coverage": Decimal("0.35"),
                "ink_specific_gravity": Decimal("1.05")}


# ---------------------------------------------------------------- small helpers

def plant_now() -> datetime:
    """Now on the demo day, plant time, naive (how ``runs`` stores datetimes)."""
    t = now().astimezone(IST)
    return datetime.combine(today(), t.time().replace(microsecond=0))


def to_plant(dt: datetime) -> datetime:
    """A request datetime -> naive IST (naive input is taken as IST already)."""
    if dt.tzinfo is not None:
        dt = dt.astimezone(IST).replace(tzinfo=None)
    return dt.replace(microsecond=0)


def _utc_iso(v: Any) -> str | None:
    """``created_at``/``updated_at`` come from the DB clock (UTC, naive) -> ISO in IST."""
    if v is None:
        return None
    if isinstance(v, str):
        v = datetime.fromisoformat(v)
    if v.tzinfo is None:
        v = v.replace(tzinfo=timezone.utc)
    return v.astimezone(IST).isoformat()


def _stops(raw: Any) -> list[dict]:
    out = []
    for s in raw or []:
        if isinstance(s, dict):
            out.append({"reason": str(s.get("reason") or ""), "minutes": int(s.get("minutes") or 0)})
    return out


def _f(v: Any, places: int = 2) -> float | None:
    return None if v is None else round(float(v), places)


# ---------------------------------------------------------------- machine hour rates

class HourRates:
    """Machine hour rate per (machine, month) = (crew + other cost) / hours run (core.rules).

    A month with no hours run yet falls back to the latest earlier month that has hours
    (same rule as ``GET /api/machines``), so a running job still shows a rate.
    """

    def __init__(self, db: Session):
        rn, cost = T("runs"), T("machine_costs")
        self.hours: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
        for r in db.execute(select(rn.c.machine_id, rn.c.start, rn.c.hours)
                            .where(rn.c.hours.is_not(None), rn.c.start.is_not(None))):
            self.hours[(r.machine_id, r.start.strftime("%Y-%m"))] += dec(r.hours)
        self.costs: dict[str, list] = defaultdict(list)
        for r in db.execute(select(cost).order_by(cost.c.month.desc())):
            self.costs[r.machine_id].append(r)
        self._cache: dict[tuple[str, str], Decimal] = {}

    def rate(self, machine_id: str, month: str) -> Decimal:
        key = (machine_id, month)
        if key not in self._cache:
            rows = [c for c in self.costs.get(machine_id, []) if c.month <= month]
            pick = next((c for c in rows if self.hours.get((machine_id, c.month), 0) > 0), None)
            if pick is None:
                self._cache[key] = Decimal("0.00")
            else:
                self._cache[key] = P.machine_hour_rate(pick.crew_salary or 0, pick.other_cost or 0,
                                                       self.hours[(machine_id, pick.month)])
        return self._cache[key]


# ---------------------------------------------------------------- runs

def _run_rows(db: Session, *where) -> list:
    rn, mc, jb, cl = T("runs"), T("machines"), T("jobs"), T("clients")
    stmt = (select(*rn.c, mc.c.name.label("machine_name"), mc.c.type.label("machine_type"),
                   mc.c.max_speed_mpm, cl.c.name.label("client_name"), jb.c.order_qty, jb.c.ups_across,
                   jb.c.ups_along, jb.c.repeat_mm)
            .select_from(rn)
            .join(mc, mc.c.id == rn.c.machine_id, isouter=True)
            .join(jb, jb.c.job_card == rn.c.job_card, isouter=True)
            .join(cl, cl.c.id == jb.c.client_id, isouter=True)
            .where(*where)
            .order_by(rn.c.start.desc(), rn.c.id.desc()))
    return db.execute(stmt).all()


def _press_printed_by_job(db: Session, cards: set[str]) -> dict[str, int]:
    """Printed totals per job, press runs only (core.rules.production.printed_total_press_only)."""
    if not cards:
        return {}
    rn, mc = T("runs"), T("machines")
    by_job: dict[str, list[dict]] = defaultdict(list)
    for r in db.execute(select(rn.c.job_card, rn.c.printed_qty, mc.c.type)
                        .join(mc, mc.c.id == rn.c.machine_id, isouter=True)
                        .where(rn.c.job_card.in_(cards))):
        by_job[r.job_card].append({"machine_type": r.type, "printed_qty": r.printed_qty})
    return {jc: P.printed_total_press_only(rows) for jc, rows in by_job.items()}


def required_m(r: Any) -> float:
    """The job's required metres (no planning extra), via core.rules; 0 when the job row is incomplete."""
    _ups, req, _plan = job_svc.metres(r.order_qty, r.ups_across, r.ups_along, r.repeat_mm, 0)
    return req


def is_press(machine_type: Any) -> bool:
    return str(machine_type or "").strip().lower() == P.PRESS


def run_dict(r: Any, tol: dict, rates: HourRates, printed_by_job: dict[str, int]) -> dict:
    """One contract ``Run``. Wastage, flags and crew cost are for press runs (SPEC 2)."""
    press = is_press(r.machine_type)
    ended = r.end is not None
    req = required_m(r) if press else 0.0
    used = dec(r.used_m) if r.used_m is not None else None
    wastage_m = wastage_pct = None
    wflag = False
    if press and ended and used is not None and req > 0:
        w = P.wastage(used, req)
        wastage_m, wastage_pct = w.metres, w.pct
        wflag = P.wastage_flag(used, req, tol["wastage_tol"])
    oflag = False
    if press and r.order_qty:
        oflag = P.overprod_flag(printed_by_job.get(r.job_card, int(r.printed_qty or 0)), r.order_qty,
                                tol["overprod_tol"])
    rate = rates.rate(r.machine_id, r.start.strftime("%Y-%m"))
    hours = dec(r.hours) if r.hours is not None else None
    crew = P.crew_cost(hours, rate) if (ended and hours is not None) else None
    return {
        "id": r.id,
        "job_card": r.job_card,
        "client_name": r.client_name or "",
        "machine_id": r.machine_id,
        "machine_name": r.machine_name or "",
        "machine_type": P.PRESS if press else "offline",
        "shift": r.shift if r.shift in SHIFTS else "day",
        "operator": r.operator or "",
        "start": jsonable(r.start),
        "end": jsonable(r.end),
        "hours": _f(hours),
        "status": "ended" if ended else "running",
        "printed_qty": int(r.printed_qty or 0),
        "required_m": req if press and req > 0 else None,
        "used_m": _f(used),
        "wastage_m": wastage_m,
        "wastage_pct": wastage_pct,
        "wastage_flag": bool(wflag),
        "overprod_flag": bool(oflag),
        "hour_rate": float(rate),
        "crew_cost": float(crew) if crew is not None else None,
        "stops": _stops(r.stops),
        "is_demo": bool(r.is_demo),
    }


def list_runs(db: Session, *, status: str | None = None, machine_id: str | None = None,
              job_card: str | None = None, run_id: str | None = None) -> list[dict]:
    rn = T("runs")
    where = []
    if status == "running":
        where.append(rn.c.end.is_(None))
    elif status == "ended":
        where.append(rn.c.end.is_not(None))
    if machine_id:
        where.append(rn.c.machine_id == machine_id)
    if job_card:
        where.append(rn.c.job_card == job_card)
    if run_id:
        where.append(rn.c.id == run_id)
    rows = _run_rows(db, *where)
    tol = job_svc.tolerances(db)
    rates = HourRates(db)
    printed = _press_printed_by_job(db, {r.job_card for r in rows})
    return [run_dict(r, tol, rates, printed) for r in rows]


def get_run(db: Session, run_id: str) -> dict | None:
    found = list_runs(db, run_id=run_id)
    return found[0] if found else None


def run_row(db: Session, run_id: str) -> Any:
    rows = _run_rows(db, T("runs").c.id == run_id)
    return rows[0] if rows else None


# ---------------------------------------------------------------- press setup

def _settings_extra(db: Session) -> dict:
    st = T("settings")
    row = db.execute(select(st.c.extra).order_by(st.c.id).limit(1)).first()
    extra = row.extra if row is not None else None
    return extra if isinstance(extra, dict) else {}


def ink_estimate_kg(db: Session, units: Iterable[dict], area_m2: Any) -> float:
    """Estimated ink (kg) for a job: per unit, anilox volume (BCM) x transfer x coverage x SG x area.

    BCM (billion cubic microns per sq inch) -> cm3 per sq m is x 1.55; cm3 x SG = grams.
    Transfer, coverage and specific gravity come from settings.extra when the client sheet
    has them, else typical flexo values (30% transfer, 35% coverage, SG 1.05).
    """
    extra = _settings_extra(db)
    k = {}
    for key, default in INK_DEFAULTS.items():
        try:
            k[key] = dec(extra[key]) if extra.get(key) not in (None, "") else default
        except (RuleError, ArithmeticError, ValueError):
            k[key] = default
    area = dec(area_m2 or 0)
    grams = Decimal(0)
    for u in units:
        bcm = dec(u.get("anilox_bcm") or 0)
        grams += bcm * BCM_TO_CM3_PER_M2 * k["anilox_transfer"] * k["ink_coverage"] \
            * k["ink_specific_gravity"] * area
    return float((grams / 1000).quantize(Decimal("0.01")))


def job_area_m2(job: dict, web_width_mm: Any) -> Decimal:
    """Printed web area for the order: required metres x web width."""
    return dec(job.get("required_m") or 0) * dec(web_width_mm or 0) / 1000


def _units_out(raw: Any) -> list[dict]:
    out = []
    for i, u in enumerate(raw or [], start=1):
        if isinstance(u, str):
            u = {"colour": u}
        if not isinstance(u, dict):
            continue
        out.append({
            "unit": int(u.get("unit") or i),
            "colour": str(u.get("colour") or ""),
            "anilox_lpi": int(u.get("anilox_lpi") or 0),
            "anilox_bcm": round(float(u.get("anilox_bcm") or 0), 2),
            "plate_id": u.get("plate_id"),
            "ink_item_id": u.get("ink_item_id"),
        })
    return out


def press_setup(db: Session, job: dict, machine_id: str | None = None) -> dict:
    """The saved setup for a job (on its planned machine, else the latest saved), or a draft
    built from the job card and design units when nothing is saved yet."""
    ps, mc, ds = T("press_setup"), T("machines"), T("design")
    stmt = select(ps, mc.c.name.label("machine_name")).join(mc, mc.c.id == ps.c.machine_id, isouter=True) \
        .where(ps.c.job_card == job["job_card"])
    if machine_id:
        stmt = stmt.where(ps.c.machine_id == machine_id)
    rows = db.execute(stmt.order_by(ps.c.updated_at.desc())).all()
    row = next((r for r in rows if r.machine_id == job["machine_id"]), rows[0] if rows else None)
    base = {"job_card": job["job_card"], "ups_across": job["ups_across"], "ups_along": job["ups_along"],
            "repeat_mm": float(job["repeat_mm"])}
    if row is not None:
        return {**base, "machine_id": row.machine_id, "machine_name": row.machine_name or "",
                "web_width_mm": int(row.web_width_mm or 0), "die_id": row.die_id, "units": _units_out(row.units),
                "speed_target_mpm": int(row.speed_target_mpm or 0), "est_ink_kg": _f(row.est_ink_kg or 0),
                "notes": row.notes or "", "updated_at": _utc_iso(row.updated_at), "updated_by": row.updated_by or ""}
    # draft: nothing saved yet
    d = db.execute(select(ds.c.units, ds.c.die_id, ds.c.updated_at).where(ds.c.job_card == job["job_card"])).first()
    raw_units = (d.units if d is not None and d.units else None) or job.get("units") or []
    units = [{**u, "anilox_bcm": u["anilox_bcm"] or 3.5, "anilox_lpi": u["anilox_lpi"] or 800}
             for u in _units_out(raw_units)]
    mid = machine_id or job["machine_id"]
    m = db.execute(select(mc.c.name, mc.c.max_speed_mpm).where(mc.c.id == mid)).first()
    width = int(job.get("paper_width_mm") or 0)
    return {**base, "machine_id": mid or "", "machine_name": (m.name if m else "") or "", "web_width_mm": width,
            "die_id": d.die_id if d is not None else None, "units": units,
            "speed_target_mpm": int(((m.max_speed_mpm or 0) * 0.5) if m else 0),
            "est_ink_kg": ink_estimate_kg(db, units, job_area_m2(job, width)), "notes": "",
            "updated_at": _utc_iso(d.updated_at) if d is not None and d.updated_at else
            datetime.combine(today(), datetime.min.time(), IST).isoformat(),
            "updated_by": ""}


# ---------------------------------------------------------------- aggregation helpers

def _wastage_totals(runs: Iterable[dict]) -> tuple[Decimal, Decimal]:
    """(used, required) over ended press runs with used metres; a job's required metres count once."""
    used_by_job: dict[str, Decimal] = defaultdict(Decimal)
    req_by_job: dict[str, Decimal] = {}
    for r in runs:
        if r["machine_type"] != P.PRESS or r["used_m"] is None or not r["required_m"]:
            continue
        used_by_job[r["job_card"]] += dec(r["used_m"])
        req_by_job[r["job_card"]] = dec(r["required_m"])
    return sum(used_by_job.values(), Decimal(0)), sum(req_by_job.values(), Decimal(0))


def _wastage(used: Decimal, req: Decimal) -> tuple[float, float]:
    if req <= 0:
        return 0.0, 0.0
    w = P.wastage(used, req)
    return w.metres, w.pct


def _day(iso_dt: str) -> date:
    return datetime.fromisoformat(iso_dt).date()


def _presses(db: Session) -> list:
    mc = T("machines")
    return [m for m in db.execute(select(mc).order_by(mc.c.id)).all() if is_press(m.type)]


# ---------------------------------------------------------------- OEE

def parse_month(month: str | None) -> tuple[str, date, date]:
    if month is None or not month.strip():
        d = today()
        month = d.strftime("%Y-%m")
    try:
        first = datetime.strptime(month.strip(), "%Y-%m").date()
    except ValueError:
        raise ValueError(f"month must be YYYY-MM, got '{month}'") from None
    last = first.replace(day=monthrange(first.year, first.month)[1])
    return first.strftime("%Y-%m"), first, min(last, today()) if first <= today() else last


def oee(db: Session, month: str | None) -> dict:
    """OEE per press for the month to date: availability x performance x quality (core.rules).

    planned = one 8 h shift per completed day; run = hours of ended runs; performance = metres
    run / (run minutes x rated speed); quality = QC approved / checked for those runs (1 when no
    QC yet).
    """
    label, first, to = parse_month(month)
    days = max((to - first).days + (0 if to == today() else 1), 0)
    planned = Decimal(days * SHIFT_HOURS)
    runs = [r for r in list_runs(db, status="ended") if first <= _day(r["start"]) <= to]
    qc = T("qc")
    run_ids = [r["id"] for r in runs]
    checked: dict[str, int] = defaultdict(int)
    approved: dict[str, int] = defaultdict(int)
    if run_ids:
        for q in db.execute(select(qc.c.run_id, qc.c.checked, qc.c.approved).where(qc.c.run_id.in_(run_ids))):
            checked[q.run_id] += int(q.checked or 0)
            approved[q.run_id] += int(q.approved or 0)
    rates = HourRates(db)
    machines, oees = [], []
    for m in _presses(db):
        mine = [r for r in runs if r["machine_id"] == m.id]
        run_h = sum((dec(r["hours"] or 0) for r in mine), Decimal(0))
        metres = sum((dec(r["used_m"] or 0) for r in mine), Decimal(0))
        chk = sum(checked[r["id"]] for r in mine)
        apr = sum(approved[r["id"]] for r in mine)
        avail = min(run_h / planned, Decimal(1)) if planned > 0 else Decimal(0)
        capacity = run_h * 60 * dec(m.max_speed_mpm or 0)
        perf = min(metres / capacity, Decimal(1)) if capacity > 0 else Decimal(0)
        qual = min(Decimal(apr) / Decimal(chk), Decimal(1)) if chk > 0 else Decimal(1)
        a, p, q = (float(x.quantize(Decimal("0.0001"))) for x in (avail, perf, qual))
        value = P.oee(a, p, q)
        if mine:  # plant OEE averages presses that ran; idle presses show their own 0 below
            oees.append(value)
        losses: dict[str, int] = defaultdict(int)
        for r in mine:
            for s in r["stops"]:
                losses[s["reason"]] += s["minutes"]
        if losses:
            top = max(sorted(losses), key=lambda k: losses[k])
            top_loss = f"{top} ({losses[top]} min)"
        elif not mine:
            top_loss = "Idle: no runs booked"
        else:
            top_loss = "No stops logged"
        machines.append({
            "machine_id": m.id, "machine_name": m.name or "", "planned_hours": float(planned),
            "run_hours": round(float(run_h), 2), "downtime_hours": round(float(max(planned - run_h, Decimal(0))), 2),
            "availability": a, "performance": p, "quality": q, "oee": value, "top_loss": top_loss,
            "hour_rate": float(rates.rate(m.id, label)),
        })
    plant = round(sum(oees) / len(oees), 4) if oees else 0.0
    return {"month": label, "from": first.isoformat(), "to": to.isoformat(), "plant_oee": plant,
            "machines": machines}


# ---------------------------------------------------------------- morning report

def morning_report(db: Session, report_date: date | None) -> dict:
    """Yesterday per press (runs by start day, so a night shift counts on its start day) + MTD."""
    d = report_date or today()
    for_date = d - timedelta(days=1)
    first = for_date.replace(day=1)
    runs = [r for r in list_runs(db) if first <= _day(r["start"]) <= for_date]
    tol = job_svc.tolerances(db)
    machines, highlights = [], []
    day_runs_all: list[dict] = []
    for m in _presses(db):
        mtd = [r for r in runs if r["machine_id"] == m.id]
        day = [r for r in mtd if _day(r["start"]) == for_date]
        day_runs_all += day
        used, req = _wastage_totals(day)
        w_m, w_pct = _wastage(used, req)
        mused, mreq = _wastage_totals(mtd)
        run_h = sum((dec(r["hours"] or 0) for r in day), Decimal(0))
        stop_min = sum(s["minutes"] for r in day for s in r["stops"])
        idle_min = max(SHIFT_HOURS * 60 - int(run_h * 60), 0)
        machines.append({
            "machine_id": m.id, "machine_name": m.name or "",
            "jobs": sorted({r["job_card"] for r in day}), "runs": len(day),
            "printed_qty": P.printed_total_press_only(day),
            "required_m": round(float(req), 2), "used_m": round(float(used), 2),
            "wastage_m": w_m, "wastage_pct": w_pct, "run_hours": round(float(run_h), 2),
            "downtime_min": int(stop_min + idle_min),
            "mtd_printed_qty": P.printed_total_press_only(mtd),
            "mtd_wastage_pct": _wastage(mused, mreq)[1],
        })
        for r in day:
            if r["wastage_flag"]:
                stops = ", ".join(f"{s['reason']} {s['minutes']} min" for s in r["stops"]) or "no stops logged"
                highlights.append({
                    "text": f"{r['job_card']} ({r['client_name']}) on {m.name} {r['shift']} shift: wastage "
                            f"{r['wastage_m']:.1f} m = {r['wastage_pct'] * 100:.1f}% vs "
                            f"{float(tol['wastage_tol']) * 100:.0f}% limit; {stops}.",
                    "severity": "high", "link": f"/jobs/{r['job_card']}"})
            if r["overprod_flag"]:
                highlights.append({"text": f"{r['job_card']} printed above order qty + "
                                           f"{float(tol['overprod_tol']) * 100:.0f}% on {m.name}.",
                                   "severity": "medium", "link": f"/jobs/{r['job_card']}"})
        if not day:
            highlights.append({"text": f"{m.name}: no runs booked on {for_date.isoformat()}.", "severity": "low",
                               "link": f"/production?machine={m.id}"})
    used, req = _wastage_totals(day_runs_all)
    w_m, w_pct = _wastage(used, req)
    totals = {"printed_qty": P.printed_total_press_only(day_runs_all), "used_m": round(float(used), 2),
              "wastage_m": w_m, "wastage_pct": w_pct,
              "run_hours": round(sum(float(x["run_hours"]) for x in machines), 2)}
    order = {"high": 0, "medium": 1, "low": 2}
    highlights.sort(key=lambda h: order[h["severity"]])
    return {"date": d.isoformat(), "for_date": for_date.isoformat(), "machines": machines, "totals": totals,
            "highlights": highlights}


# ---------------------------------------------------------------- live counter (simulated)

def counter_seed(r: Any, setup_speed: int | None) -> dict:
    """Everything the simulated counter needs, read once before streaming (no DB in the generator)."""
    total_ups = int(r.ups_across or 0) * int(r.ups_along or 0)
    repeat = float(r.repeat_mm or 0)
    count = int(r.printed_qty or 0)
    metres = count / total_ups * repeat / 1000 if total_ups and repeat else 0.0
    speed = float(setup_speed or 0) or float(r.max_speed_mpm or 0) * 0.5 or 50.0
    return {"run_id": r.id, "count": count, "metres": metres, "speed": speed, "ups": total_ups,
            "repeat_mm": repeat, "ended": r.end is not None,
            "end_ts": jsonable(r.end) if r.end is not None else None}


def counter_tick(seed: dict, i: int, interval_s: float) -> dict:
    """Tick ``i`` of a running run: speed wobbles around target, metres and labels add up."""
    if seed["ended"]:
        return {"run_id": seed["run_id"], "ts": seed["end_ts"], "count": seed["count"],
                "metres": round(seed["metres"], 2), "speed_mpm": 0.0, "status": "ended"}
    stopped = i > 0 and i % 45 == 0  # a short stop now and then, so the board shows it
    speed = 0.0 if stopped else round(seed["speed"] * (1 + 0.02 * math.sin(i / 3)), 1)
    if i > 0:
        step_m = speed * interval_s / 60
        seed["metres"] += step_m
        if seed["repeat_mm"] > 0:
            seed["count"] = int(seed["metres"] * 1000 / seed["repeat_mm"] * seed["ups"])
    return {"run_id": seed["run_id"], "ts": now().isoformat(), "count": seed["count"],
            "metres": round(seed["metres"], 2), "speed_mpm": speed, "status": "stopped" if stopped else "running"}
