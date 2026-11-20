"""Job register, job card creation and the planning material summary (SPEC 2 and 3, issue #15).

All metres, money, stock and tolerance maths goes through ``core.rules``; this module only
gathers rows and shapes contract JSON (``Job``, ``MaterialSummary`` in contract/openapi.yaml).
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.deps import T, today
from app.routers.shell import load_settings
from app.serialize import money
from app.services.clients import client_locks
from core.rules import production as P
from core.rules import quality as Q
from core.rules import store as S
from core.rules.errors import RuleError, dec
from core.rules.settings import DEFAULTS

JOB_STATUSES = ("planned", "design", "printing", "qc", "dispatch", "invoiced", "closed", "hold")
# Jobs that still need paper from the store (planned_m - issued_m > 0); hold jobs wait.
OPEN_FOR_MATERIAL = ("planned", "design", "printing")
DONE = ("invoiced", "closed")
FLAG_ORDER = ("wastage_high", "material_variance", "overprod", "material_short", "client_locked", "qc_hold",
              "late")


# ---------------------------------------------------------------- settings helpers

def tolerances(db: Session) -> dict[str, Any]:
    s = load_settings(db)
    out: dict[str, Any] = {}
    for key in ("planning_extra", "wastage_tol", "overprod_tol", "material_tol"):
        v = s.get(key)
        out[key] = float(v) if v is not None else getattr(DEFAULTS, key)
    raw = s.get("stock_from")
    out["stock_from"] = date.fromisoformat(raw) if isinstance(raw, str) else raw
    return out


def metres(order_qty: Any, ups_across: Any, ups_along: Any, repeat_mm: Any,
           planning_extra: float) -> tuple[int, float, float]:
    """(ups, required_m, planned_m) via core.rules.production; zeros for an incomplete job row."""
    try:
        total_ups = P.ups(int(ups_across or 0), int(ups_along or 0))
        req = P.required_metres(order_qty or 0, total_ups, repeat_mm or 0)
        plan = P.planned_metres(order_qty or 0, total_ups, repeat_mm or 0, planning_extra)
    except RuleError:
        total_ups = int(ups_across or 0) * int(ups_along or 0)
        return total_ups, 0.0, 0.0
    return total_ups, req, plan


# ---------------------------------------------------------------- aggregates

def _sum_by_job(db: Session, table: str, col: str, cards: set[str] | None, *where) -> dict[str, float]:
    t = T(table)
    stmt = select(t.c.job_card, func.sum(t.c[col])).where(t.c.job_card.is_not(None), *where)
    if cards is not None:
        stmt = stmt.where(t.c.job_card.in_(cards))
    return {jc: float(v or 0) for jc, v in db.execute(stmt.group_by(t.c.job_card))}


def _aggregates(db: Session, cards: set[str] | None) -> dict[str, dict]:
    runs, machines, qc = T("runs"), T("machines"), T("qc")
    agg: dict[str, dict] = defaultdict(lambda: {"issued": 0.0, "printed": 0, "used": 0.0, "qc": [],
                                                "dispatched": 0, "invoiced": 0})
    for jc, v in _sum_by_job(db, "issues", "qty", cards).items():
        agg[jc]["issued"] = v
    run_rows = select(runs.c.job_card, runs.c.machine_id, runs.c.printed_qty, runs.c.used_m, machines.c.type) \
        .join(machines, machines.c.id == runs.c.machine_id, isouter=True)
    if cards is not None:
        run_rows = run_rows.where(runs.c.job_card.in_(cards))
    by_job: dict[str, list[dict]] = defaultdict(list)
    for jc, _m, printed, used, mtype in db.execute(run_rows):
        by_job[jc].append({"machine_type": mtype, "printed_qty": printed, "used_m": used})
    for jc, rows in by_job.items():
        agg[jc]["printed"] = P.printed_total_press_only(rows)
        agg[jc]["used"] = float(sum(dec(r["used_m"] or 0) for r in rows
                                    if str(r["machine_type"] or "").lower() == P.PRESS))
    qc_rows = select(qc.c.job_card, qc.c.approved, qc.c.decision)
    if cards is not None:
        qc_rows = qc_rows.where(qc.c.job_card.in_(cards))
    for jc, approved, decision in db.execute(qc_rows):
        agg[jc]["qc"].append({"approved_qty": approved, "decision": decision})
    for jc, v in _sum_by_job(db, "dispatches", "qty", cards).items():
        agg[jc]["dispatched"] = int(v)
    for jc, v in _sum_by_job(db, "invoices", "qty", cards).items():
        agg[jc]["invoiced"] = int(v)
    return agg


def stock_by_item(db: Session, item_ids: Iterable[str], stock_from: date | None) -> dict[str, float]:
    """Stock = opening (as of stock_from) + received - issued, via core.rules.store.stock_balance."""
    ids = set(item_ids)
    if not ids:
        return {}
    op, grns, issues = T("opening_stock"), T("grns"), T("issues")
    opening: dict[str, Decimal] = defaultdict(Decimal)
    stmt = select(op.c.item_id, op.c.qty, op.c.as_of).where(op.c.item_id.in_(ids))
    for iid, qty, as_of in db.execute(stmt):
        if stock_from is None or as_of is None or as_of == stock_from:
            opening[iid] += dec(qty or 0)

    def moves(t) -> dict[str, list]:
        out: dict[str, list] = defaultdict(list)
        s = select(t.c.item_id, t.c.qty).where(t.c.item_id.in_(ids))
        if stock_from is not None:
            s = s.where(t.c.date >= stock_from)
        for iid, qty in db.execute(s):
            out[iid].append(qty or 0)
        return out

    received, issued = moves(grns), moves(issues)
    return {iid: float(S.stock_balance(opening[iid], received[iid], issued[iid])) for iid in ids}


# ---------------------------------------------------------------- material summary

def material_summary(db: Session, jobs: list[dict] | None = None, tol: dict | None = None) -> dict:
    """Paper needed by open jobs (planned_m - issued_m, planned includes +planning_extra) vs stock."""
    tol = tol or tolerances(db)
    if jobs is None:
        jobs = list_jobs(db, with_flags=False, tol=tol)
    need_jobs: dict[str, list[dict]] = defaultdict(list)
    for j in jobs:
        if j["status"] not in OPEN_FOR_MATERIAL:
            continue
        need = dec(j["planned_m"]) - dec(j["issued_m"])
        if need > 0 and j["item_id"]:
            need_jobs[j["item_id"]].append({"job_card": j["job_card"], "client_name": j["client_name"],
                                            "need_m": float(need.quantize(Decimal("0.01")))})
    items_t = T("items")
    names = {r.id: r for r in db.execute(select(items_t.c.id, items_t.c.name, items_t.c.width_mm)
                                         .where(items_t.c.id.in_(set(need_jobs))))}
    stock = stock_by_item(db, need_jobs, tol["stock_from"])
    items = []
    for iid in sorted(need_jobs):
        rows = sorted(need_jobs[iid], key=lambda r: r["job_card"])
        need = sum((dec(r["need_m"]) for r in rows), Decimal(0))
        have = dec(stock.get(iid, 0))
        short = max(need - have, Decimal(0))
        it = names.get(iid)
        items.append({
            "item_id": iid,
            "material": (it.name if it else None) or iid,
            "width_mm": int((it.width_mm if it else None) or 0),
            "jobs": rows,
            "need_m": float(need.quantize(Decimal("0.01"))),
            "stock_m": float(have.quantize(Decimal("0.01"))),
            "shortage_m": float(short.quantize(Decimal("0.01"))),
            "status": "short" if short > 0 else "ok",
        })
    return {
        "as_of": today().isoformat(),
        "planning_extra": round(float(tol["planning_extra"]), 4),
        "items": items,
        "shortages": sum(1 for i in items if i["status"] == "short"),
    }


# ---------------------------------------------------------------- jobs

def _iso(v: Any) -> str | None:
    return v.isoformat() if isinstance(v, date) else v


def _job_dict(r: Any, agg: dict, tol: dict) -> dict:
    total_ups, req, plan = metres(r.order_qty, r.ups_across, r.ups_along, r.repeat_mm, tol["planning_extra"])
    a = agg.get(r.job_card) or {"issued": 0.0, "printed": 0, "used": 0.0, "qc": [], "dispatched": 0,
                                "invoiced": 0}
    return {
        "job_card": r.job_card,
        "created_on": _iso(r.created_on),
        "client_id": r.client_id or "",
        "client_name": r.client_name or "",
        "po_no": r.po_no or "",
        "po_date": _iso(r.po_date),
        "product": r.product or "",
        "label_size": r.label_size or "",
        "order_qty": int(r.order_qty or 0),
        "rate": money(r.rate),
        "po_value": float(_po_value(r.order_qty, r.rate)),
        "item_id": r.item_id or "",
        "material": r.material or "",
        "paper_width_mm": int(r.paper_width_mm or 0),
        "machine_id": r.machine_id or "",
        "machine_name": r.machine_name or "",
        "ups_across": int(r.ups_across or 0),
        "ups_along": int(r.ups_along or 0),
        "ups": total_ups,
        "repeat_mm": float(r.repeat_mm or 0),
        "units": list(r.units or []),
        "required_m": req,
        "planned_m": plan,
        "issued_m": round(a["issued"], 2),
        "printed_qty": int(a["printed"]),
        "qc_approved": Q.approved_total(a["qc"]),
        "dispatched_qty": int(a["dispatched"]),
        "invoiced_qty": int(a["invoiced"]),
        "status": r.status if r.status in JOB_STATUSES else "planned",
        "priority": r.priority if r.priority in ("high", "normal", "low") else "normal",
        "due_date": _iso(r.due_date),
        "enquiry_id": r.enquiry_id,
        "quote_id": r.quote_id,
        "flags": [],
        "is_demo": bool(r.is_demo),
        "_used_m": a["used"],
        "_qc_hold": any(str(q["decision"] or "").strip().lower() == "hold" for q in a["qc"]),
    }


def _po_value(order_qty: Any, rate: Any) -> Decimal:
    from core.rules.money import po_value

    return po_value(order_qty or 0, rate or 0)


def _flags(j: dict, tol: dict, short_jobs: set[str], locked: dict[str, bool]) -> list[str]:
    flags: set[str] = set()
    req, used, issued = j["required_m"], j.pop("_used_m"), j["issued_m"]
    qc_hold = j.pop("_qc_hold")
    open_job = j["status"] not in DONE
    if used > 0 and req > 0 and P.wastage_flag(used, req, tol["wastage_tol"]):
        flags.add("wastage_high")
    if issued > 0 and P.material_flag(issued, j["planned_m"], tol["material_tol"]):
        flags.add("material_variance")
    if j["printed_qty"] > 0 and P.overprod_flag(j["printed_qty"], j["order_qty"], tol["overprod_tol"]):
        flags.add("overprod")
    if j["job_card"] in short_jobs:
        flags.add("material_short")
    if open_job and locked.get(j["client_id"]):
        flags.add("client_locked")
    if open_job and qc_hold:
        flags.add("qc_hold")
    if open_job and j["due_date"] and j["due_date"] < today().isoformat() and j["dispatched_qty"] < j["order_qty"]:
        flags.add("late")
    return [f for f in FLAG_ORDER if f in flags]


def _select_jobs():
    jobs, clients, items, machines = T("jobs"), T("clients"), T("items"), T("machines")
    return (
        select(*jobs.c, clients.c.name.label("client_name"), items.c.name.label("material"),
               items.c.width_mm.label("paper_width_mm"), machines.c.name.label("machine_name"))
        .select_from(jobs)
        .join(clients, clients.c.id == jobs.c.client_id, isouter=True)
        .join(items, items.c.id == jobs.c.item_id, isouter=True)
        .join(machines, machines.c.id == jobs.c.machine_id, isouter=True)
    )


def list_jobs(db: Session, *, status: str | None = None, q: str | None = None, job_card: str | None = None,
              client_id: str | None = None, with_flags: bool = True, tol: dict | None = None) -> list[dict]:
    """Contract ``Job`` dicts, filtered by status / text / one job card / one client."""
    tol = tol or tolerances(db)
    jobs, clients = T("jobs"), T("clients")
    stmt = _select_jobs()
    if client_id:
        stmt = stmt.where(jobs.c.client_id == client_id)
    if status:
        stmt = stmt.where(jobs.c.status == status)
    if job_card:
        stmt = stmt.where(jobs.c.job_card == job_card)
    if q and q.strip():
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(func.lower(jobs.c.job_card).like(like) | func.lower(clients.c.name).like(like)
                          | func.lower(jobs.c.product).like(like) | func.lower(jobs.c.po_no).like(like))
    rows = db.execute(stmt.order_by(jobs.c.created_on, jobs.c.job_card)).all()
    cards = {r.job_card for r in rows} if (job_card or status or q or client_id) else None
    agg = _aggregates(db, cards)
    out = [_job_dict(r, agg, tol) for r in rows]
    if not with_flags:
        for j in out:
            j.pop("_used_m", None)
            j.pop("_qc_hold", None)
        return out
    # material_short needs every open job (the shortage is per paper, across jobs)
    all_open = out if cards is None else list_jobs(db, with_flags=False, tol=tol)
    summary = material_summary(db, [j for j in all_open if j["status"] in OPEN_FOR_MATERIAL], tol)
    short_jobs = {jb["job_card"] for it in summary["items"] if it["status"] == "short" for jb in it["jobs"]}
    ids = {j["client_id"] for j in out if j["status"] not in DONE and j["client_id"]}
    locked = {cid: lk.get("lock_status") == "locked" for cid, lk in client_locks(db, ids).items()} if ids else {}
    for j in out:
        j["flags"] = _flags(j, tol, short_jobs, locked)
    return out


def get_job(db: Session, job_card: str) -> dict | None:
    found = list_jobs(db, job_card=job_card)
    return found[0] if found else None
