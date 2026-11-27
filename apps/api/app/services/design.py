"""Design register, Plate Store and Die Store (SPEC 3 "Design"; schema.md: design, plates, dies).

Read helpers return contract dicts (``Design``, ``Plate``, ``Die`` in openapi.yaml) so other
routers (Job 360, search) can reuse them. :func:`update_design` applies a ``DesignUpdate``
with the plant's design rules (Automation Plan, "v12 rules kept"):

- stages run in order: artwork -> proof_sent -> approved -> plates_ordered -> plates_ready -> done;
  a stage may be skipped forward only when what it needs is given, never moved back
  (except back to ``artwork`` with a new ``artwork_version``);
- approval (``approved_on`` + ``approved_by``) is required before plates;
- the die must exist in the Die Store (and not be scrapped/damaged), plates in the Plate Store;
- the route's print step must name the job's planned press ("route matches division");
- units/colours and route text default from the job card when not given.
"""
from __future__ import annotations

from datetime import date, datetime, time
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.audit import audit, next_id
from app.deps import T, bad_request, not_found, today
from app.serialize import IST, jsonable, money, now

STAGES = ("artwork", "proof_sent", "approved", "plates_ordered", "plates_ready", "done")
EDITABLE = ("stage", "designer", "artwork_version", "proof_sent_on", "approved_on", "approved_by",
            "die_id", "units", "route", "notes")
UNUSABLE_DIE = ("damaged", "scrapped")
UNUSABLE_PLATE = ("damaged", "scrapped")
DEFAULT_LPI = 800


# ---------------------------------------------------------------- lookups

def _job(db: Session, job_card: str):
    jobs, clients = T("jobs"), T("clients")
    q = (select(jobs, clients.c.name.label("client_name"))
         .select_from(jobs.outerjoin(clients, clients.c.id == jobs.c.client_id))
         .where(jobs.c.job_card == job_card))
    return db.execute(q).first()


def _machine(db: Session, machine_id: str | None):
    if not machine_id:
        return None
    m = T("machines")
    return db.execute(select(m).where(m.c.id == machine_id)).first()


def _design_row(db: Session, job_card: str):
    d = T("design")
    return db.execute(select(d).where(d.c.job_card == job_card)).first()


def _int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _units(raw: Any) -> list[dict]:
    out = []
    for i, u in enumerate(raw or [], start=1):
        if isinstance(u, str):  # tolerate a bare colour list
            u = {"unit": i, "colour": u}
        if not isinstance(u, dict):
            continue
        lpi = u.get("anilox_lpi")
        out.append({"unit": _int(u.get("unit"), i), "colour": str(u.get("colour") or ""),
                    "anilox_lpi": None if lpi is None else _int(lpi),
                    "plate_id": u.get("plate_id") or None})
    return sorted(out, key=lambda x: x["unit"])


def _default_units(job: Any) -> list[dict]:
    colours = job._mapping.get("units") or []
    return [{"unit": n, "colour": str(c), "anilox_lpi": DEFAULT_LPI, "plate_id": None}
            for n, c in enumerate(colours, start=1)]


def _default_route(press_name: str | None) -> list[str]:
    return ([f"Print {press_name}"] if press_name else []) + ["Inspection RW-1", "Pack"]


def _plates_made_for(db: Session, job_card: str) -> list[str]:
    p = T("plates")
    return [r[0] for r in db.execute(select(p.c.id).where(p.c.job_card == job_card).order_by(p.c.unit, p.c.id))]


def _stamp(row_map: Any, job_map: Any) -> str:
    ts = row_map.get("updated_at") or row_map.get("created_at") if row_map is not None else None
    if ts is None:
        days = [d for d in ((row_map or {}).get("approved_on"), (row_map or {}).get("proof_sent_on"),
                            job_map.get("created_on")) if isinstance(d, date)]
        ts = datetime.combine(max(days), time(9, 0), tzinfo=IST) if days else now()
    return jsonable(ts)


def _record(db: Session, job: Any, row: Any) -> dict:
    """One ``Design`` contract dict from a job row and its design row (or defaults when none)."""
    jm = job._mapping
    rm = row._mapping if row is not None else None
    press = _machine(db, jm.get("machine_id"))
    units = _units(rm.get("units")) if rm is not None and rm.get("units") else _default_units(job)
    route = list(rm.get("route") or []) if rm is not None else []
    if not route:
        route = _default_route(press._mapping["name"] if press is not None else None)
    plate_ids: list[str] = []
    for pid in [u["plate_id"] for u in units if u["plate_id"]] + _plates_made_for(db, jm["job_card"]):
        if pid not in plate_ids:
            plate_ids.append(pid)
    get = (lambda k, dflt=None: rm.get(k) if rm.get(k) is not None else dflt) if rm is not None \
        else (lambda _k, dflt=None: dflt)
    stage = get("stage", "artwork")
    return {
        "job_card": jm["job_card"],
        "client_name": jm.get("client_name") or "",
        "product": jm.get("product") or "",
        "stage": stage if stage in STAGES else "artwork",
        "designer": get("designer", ""),
        "artwork_version": _int(get("artwork_version", 1), 1),
        "proof_sent_on": jsonable(get("proof_sent_on")),
        "approved_on": jsonable(get("approved_on")),
        "approved_by": get("approved_by"),
        "repeat_mm": round(float(jm.get("repeat_mm") or 0), 3),
        "ups_across": _int(jm.get("ups_across")),
        "ups_along": _int(jm.get("ups_along")),
        "die_id": get("die_id"),
        "plate_ids": plate_ids,
        "units": units,
        "route": [str(s) for s in route],
        "notes": get("notes", ""),
        "updated_at": _stamp(rm, jm),
        "is_demo": bool(get("is_demo", jm.get("is_demo") or False)),
    }


# ---------------------------------------------------------------- reads

NEW_JOB_STATUSES = ("planned", "design")


def list_design(db: Session, stage: str | None = None) -> list[dict]:
    d, jobs = T("design"), T("jobs")
    # Every job with a design record, plus new jobs (planned / in design) that have none yet: they
    # start at the artwork stage, so Design can pick them up (a new job card must show up here).
    q = (select(jobs.c.job_card)
         .select_from(jobs.outerjoin(d, d.c.job_card == jobs.c.job_card))
         .where(or_(d.c.job_card.is_not(None), jobs.c.status.in_(NEW_JOB_STATUSES))))
    out = []
    for (jc,) in db.execute(q):
        job = _job(db, jc)
        if job is not None:
            rec = _record(db, job, _design_row(db, jc))
            if not stage or rec["stage"] == stage:
                out.append(rec)
    order = {s: i for i, s in enumerate(STAGES)}
    # work queue first: earliest stage, then most recently touched, then job card
    out.sort(key=lambda r: r["job_card"], reverse=True)
    out.sort(key=lambda r: r["updated_at"], reverse=True)
    out.sort(key=lambda r: order.get(r["stage"], 0))
    return out


def get_design(db: Session, job_card: str) -> dict:
    job = _job(db, job_card)
    if job is None:
        raise not_found("job", job_card)
    return _record(db, job, _design_row(db, job_card))


def list_plates(db: Session) -> list[dict]:
    p, jobs, clients = T("plates"), T("jobs"), T("clients")
    q = (select(p, clients.c.name.label("client_name"))
         .select_from(p.outerjoin(jobs, jobs.c.job_card == p.c.job_card)
                      .outerjoin(clients, clients.c.id == jobs.c.client_id))
         .order_by(p.c.id))
    out = []
    for r in db.execute(q):
        m = r._mapping
        out.append({"id": m["id"], "job_card": m["job_card"] or "", "client_name": m["client_name"] or "",
                    "unit": _int(m["unit"]), "colour": m["colour"] or "", "made_on": jsonable(m["made_on"]),
                    "vendor_id": m["vendor_id"] or "", "cost": money(m["cost"]),
                    "impressions": _int(m["impressions"]), "status": m["status"] or "stored",
                    "rack": m["rack"] or "", "is_demo": bool(m["is_demo"])})
    return out


def list_dies(db: Session) -> list[dict]:
    dt = T("dies")
    out = []
    for r in db.execute(select(dt).order_by(dt.c.id)):
        m = r._mapping
        out.append({"id": m["id"], "type": m["type"] or "rotary", "label_size": m["label_size"] or "",
                    "ups_across": _int(m["ups_across"]), "ups_along": _int(m["ups_along"]),
                    "repeat_mm": round(float(m["repeat_mm"] or 0), 3), "vendor_id": m["vendor_id"] or "",
                    "cost": money(m["cost"]), "made_on": jsonable(m["made_on"]),
                    "last_job_card": m["last_job_card"], "impressions": _int(m["impressions"]),
                    "status": m["status"] or "ok", "location": m["location"] or "", "is_demo": bool(m["is_demo"])})
    return out


# ---------------------------------------------------------------- write

def _check_units(db: Session, units: list[dict], press: Any) -> None:
    nums = [u["unit"] for u in units]
    if any(n < 1 for n in nums):
        raise bad_request("unit numbers start at 1")
    if len(set(nums)) != len(nums):
        raise bad_request("each print unit may appear only once")
    if any(not u["colour"].strip() for u in units):
        raise bad_request("every unit needs a colour")
    if press is not None:
        pm = press._mapping
        cap = _int(pm.get("units"))
        if pm.get("type") == "press" and cap and max(nums, default=0) > cap:
            raise bad_request(f"{pm['name']} has only {cap} print units")
    pids = [u["plate_id"] for u in units if u["plate_id"]]
    if len(set(pids)) != len(pids):
        raise bad_request("a plate can be mounted on one unit only")
    if pids:
        p = T("plates")
        found = {r[0]: r[1] for r in db.execute(select(p.c.id, p.c.status).where(p.c.id.in_(pids)))}
        for pid in pids:
            if pid not in found:
                raise bad_request(f"plate {pid} is not in the Plate Store")
            if found[pid] in UNUSABLE_PLATE:
                raise bad_request(f"plate {pid} is {found[pid]}")


def _check_die(db: Session, die_id: str) -> None:
    dt = T("dies")
    row = db.execute(select(dt.c.status).where(dt.c.id == die_id)).first()
    if row is None:
        raise bad_request(f"die {die_id} is not in the Die Store")
    if row[0] in UNUSABLE_DIE:
        raise bad_request(f"die {die_id} is {row[0]}")


def _check_route(route: list[str], press: Any) -> None:
    if not route:
        raise bad_request("route needs at least one step")
    prints = [s[len("print "):].strip() for s in route if s.lower().startswith("print ")]
    if press is None:
        return
    name = press._mapping["name"]
    if not prints:
        raise bad_request(f"route must start with the print step on the job's press: 'Print {name}'")
    wrong = [p for p in prints if p.lower() != str(name).lower()]
    if wrong:
        raise bad_request(f"route prints on {wrong[0]} but the job is planned on {name}")
    if not route[0].lower().startswith("print "):
        raise bad_request("the print step must come first in the route")


def _check_stage(old: str, new: dict, version_up: bool) -> None:
    """Stage order and what each stage needs (checked on the merged record)."""
    stage = new["stage"]
    i_old, i_new = STAGES.index(old), STAGES.index(stage)
    if i_new < i_old and not (stage == "artwork" and version_up):
        raise bad_request(f"stage cannot go back from {old} to {stage} "
                          "(start a new artwork version to restart)")
    if i_new >= STAGES.index("proof_sent") and not new["proof_sent_on"]:
        raise bad_request("proof_sent_on is required once the proof is sent")
    if i_new >= STAGES.index("approved"):
        if not new["approved_on"] or not new["approved_by"]:
            what = "plates" if i_new > STAGES.index("approved") else "approved"
            raise bad_request(f"client approval (approved_on, approved_by) is required before {what}")
    if i_new >= STAGES.index("plates_ready"):
        if not new["units"]:
            raise bad_request("plates_ready needs the colour units (press set-up) first")
        missing = [u["unit"] for u in new["units"] if not u["plate_id"]]
        if missing:
            raise bad_request(f"plates_ready needs a plate on every unit (missing on unit {missing[0]})")
    if stage == "done" and not new["die_id"]:
        raise bad_request("a die from the Die Store is required to finish design")


def update_design(db: Session, job_card: str, changes: dict, role: str) -> dict:
    """Apply a ``DesignUpdate`` (only the keys sent) and audit ``design_update``."""
    job = _job(db, job_card)
    if job is None:
        raise not_found("job", job_card)
    row = _design_row(db, job_card)
    current = _record(db, job, row)
    press = _machine(db, job._mapping.get("machine_id"))
    changes = {k: v for k, v in changes.items() if k in EDITABLE}

    if "units" in changes:
        changes["units"] = _units(changes["units"] or [])
        if not changes["units"]:
            raise bad_request("at least one print unit is required")
    if "route" in changes:
        changes["route"] = [str(s).strip() for s in (changes["route"] or []) if str(s).strip()]
    for k in ("designer", "notes"):
        if k in changes and changes[k] is None:
            changes[k] = ""
    if "stage" in changes and changes["stage"] is None:
        raise bad_request("stage cannot be empty")
    if "artwork_version" in changes:
        if changes["artwork_version"] is None or changes["artwork_version"] < 1:
            raise bad_request("artwork_version starts at 1")
        if changes["artwork_version"] < current["artwork_version"]:
            raise bad_request("artwork_version cannot go down")

    merged = {**current, **changes}
    for k in ("proof_sent_on", "approved_on"):
        if isinstance(merged[k], str):
            merged[k] = date.fromisoformat(merged[k])
    if merged["proof_sent_on"] and merged["approved_on"] and merged["approved_on"] < merged["proof_sent_on"]:
        raise bad_request("approved_on cannot be before proof_sent_on")

    if "units" in changes:
        _check_units(db, merged["units"], press)
        if any(u["plate_id"] for u in merged["units"]) and STAGES.index(merged["stage"]) < STAGES.index("approved"):
            raise bad_request("client approval is required before plates")
    if changes.get("die_id"):
        _check_die(db, changes["die_id"])
    if "route" in changes:
        _check_route(merged["route"], press)
    stage_moved = "stage" in changes and changes["stage"] != current["stage"]
    new_plates: list[dict] = []
    if stage_moved:
        new_plates = _auto_plates_and_die(db, job, merged, changes)
    if stage_moved or any(k in changes for k in ("proof_sent_on", "approved_on", "approved_by")):
        version_up = merged["artwork_version"] > current["artwork_version"]
        _check_stage(current["stage"], merged, version_up)

    before = {k: current[k] for k in changes if jsonable(current[k]) != jsonable(merged[k])}
    after = {k: jsonable(merged[k]) for k in before}
    if not before and row is not None:
        return current

    d = T("design")
    values = {k: merged[k] for k in EDITABLE}
    values["updated_at"] = now()
    if row is None:
        values |= {"job_card": job_card, "created_at": values["updated_at"],
                   "is_demo": bool(job._mapping.get("is_demo") or False)}
        db.execute(d.insert().values({k: v for k, v in values.items() if k in d.c}))
    else:
        db.execute(d.update().where(d.c.job_card == job_card)
                   .values({k: v for k, v in values.items() if k in d.c}))
    _save_plates(db, merged, new_plates)
    if "units" in changes:  # keep the job card's colours in step with Design (Job 360 shows both)
        jobs = T("jobs")
        db.execute(jobs.update().where(jobs.c.job_card == job_card)
                   .values(units=[u["colour"] for u in sorted(merged["units"], key=lambda u: u["unit"])]))
    audit(db, role=role, action="design_update", entity="design", entity_id=job_card,
          before=before, after=after)
    db.commit()
    return get_design(db, job_card)


def _job_plates(db: Session, job_card: str) -> dict[int, dict]:
    """This job's usable plates by unit (latest first)."""
    p = T("plates")
    out: dict[int, dict] = {}
    rows = db.execute(select(p).where(p.c.job_card == job_card).order_by(p.c.id.desc())).mappings()
    for r in rows:
        if r["status"] not in UNUSABLE_PLATE and r["unit"] is not None and r["unit"] not in out:
            out[r["unit"]] = dict(r)
    return out


def _auto_plates_and_die(db: Session, job: Any, merged: dict, changes: dict) -> list[dict]:
    """Stage moves done from the Design screen fill what the stage needs (SPEC 2 rules unchanged):

    * ``plates_ordered``: one plate per colour unit is ordered in the Plate Store (status ``ordered``,
      cost = this plant's average plate cost, so job profit counts the plates).
    * ``plates_ready``: the job's plates are mounted on their units (status ``in_use``).
    * ``done`` without a die: a usable Die Store die with the job's label size and ups is assigned.
    Returns the plates to insert (written only after every check has passed).
    """
    stage = merged["stage"]
    jm = job._mapping
    to_insert: list[dict] = []
    if stage == "plates_ordered":
        have = _job_plates(db, jm["job_card"])
        p = T("plates")
        avg_cost, vendor = db.execute(select(func.avg(p.c.cost), func.max(p.c.vendor_id))).one()
        start = int(next_id(db, "plates", "PL", 5).split("-")[1])
        for u in (u for u in merged["units"] if u["unit"] not in have):
            to_insert.append({"id": f"PL-{start + len(to_insert):05d}", "job_card": jm["job_card"],
                              "unit": u["unit"], "colour": u["colour"], "made_on": None, "vendor_id": vendor,
                              "cost": round(float(avg_cost or 0), 2), "impressions": 0, "status": "ordered",
                              "rack": "Incoming", "is_demo": bool(jm.get("is_demo") or False)})
    if STAGES.index(stage) >= STAGES.index("plates_ready"):
        have = _job_plates(db, jm["job_card"])
        units = [dict(u) for u in merged["units"]]
        for u in units:
            if not u["plate_id"] and u["unit"] in have:
                u["plate_id"] = have[u["unit"]]["id"]
        if units != merged["units"]:
            merged["units"] = units
            changes["units"] = units
    if stage == "done" and not merged.get("die_id"):
        dt = T("dies")
        cands = db.execute(select(dt.c.id, dt.c.status).where(
            dt.c.label_size == jm.get("label_size"), dt.c.ups_across == jm.get("ups_across"),
            dt.c.ups_along == jm.get("ups_along"))).all()
        usable = sorted((r for r in cands if r[1] not in UNUSABLE_DIE), key=lambda r: (r[1] != "ok", r[0]))
        if usable:
            merged["die_id"] = usable[0][0]
            changes["die_id"] = usable[0][0]
    return to_insert


def _save_plates(db: Session, merged: dict, new_plates: list[dict]) -> None:
    p = T("plates")
    if new_plates:
        db.execute(p.insert(), new_plates)
    if STAGES.index(merged["stage"]) >= STAGES.index("plates_ready"):
        mounted = [u["plate_id"] for u in merged["units"] if u["plate_id"]]
        if mounted:
            db.execute(p.update().where(p.c.id.in_(mounted), p.c.status == "ordered")
                       .values(status="in_use", made_on=today(), rack="On press"))
