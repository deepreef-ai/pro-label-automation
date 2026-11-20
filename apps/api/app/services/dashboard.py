"""Owner dashboard KPIs, rule-based alerts and the floor TV board (SPEC 3, issue #17).

Rows come from the owning services (jobs, clients, production, store, profit); money,
wastage, OEE and tolerance maths is ``core.rules``. Shapes: ``DashboardSummary``,
``AlertsResponse`` and ``FloorBoard`` in contract/openapi.yaml (plus a few additive fields).
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.deps import T, today
from app.routers.shell import load_settings
from app.serialize import IST, now
from app.services import jobs as jobs_svc
from app.services import production as prod
from app.services import store as store_svc
from app.services.clients import client_locks, invoice_dicts
from app.services.job360 import day_label, num, pct, rs
from app.services.profit import jobs_profit
from core.rules import money as M
from core.rules import production as P
from core.rules.errors import dec, ratio
from core.rules.settings import DEFAULTS

PERIODS = ("today", "month", "year")
ZERO = Decimal("0.00")
TOP_N = 5


# ---------------------------------------------------------------- small helpers

def _frac(v: Decimal | float) -> float:
    return float(Decimal(str(v)).quantize(Decimal("0.0001")))


def _money(v: Any) -> float:
    return float(M.money(v or 0))


def _day(iso_dt: str) -> date:
    return datetime.fromisoformat(iso_dt).date()


def fy_start(db: Session, d: date) -> date:
    """Start of the financial year containing ``d`` (April, unless settings.fy_start says otherwise)."""
    raw = load_settings(db).get("fy_start")
    month = date.fromisoformat(raw).month if isinstance(raw, str) and raw else (raw.month if raw else 4)
    year = d.year if d.month >= month else d.year - 1
    return date(year, month, 1)


def period_bounds(db: Session, period: str) -> tuple[date, date]:
    t = today()
    if period == "today":
        return t, t
    if period == "month":
        return t.replace(day=1), t
    return fy_start(db, t), t


def wastage_pct(runs: Iterable[dict]) -> float:
    """Wastage % over ended press runs: total used vs total required (a job's required counts once)."""
    used: dict[str, Decimal] = defaultdict(Decimal)
    req: dict[str, Decimal] = {}
    for r in runs:
        if r["machine_type"] != P.PRESS or r["used_m"] is None or not r["required_m"]:
            continue
        used[r["job_card"]] += dec(r["used_m"])
        req[r["job_card"]] = dec(r["required_m"])
    total_req = sum(req.values(), Decimal(0))
    if total_req <= 0:
        return 0.0
    return P.wastage(sum(used.values(), Decimal(0)), total_req).pct


def payables(db: Session) -> list[dict]:
    """Open supplier bills: due by the MSME rule (core.rules.money.supplier_due_date), balance after
    FIFO payment allocations."""
    sb, v, pa = T("supplier_bills"), T("vendors"), T("payment_allocations")
    msme_days = load_settings(db).get("msme_days") or DEFAULTS.msme_days
    paid: dict[str, Decimal] = defaultdict(Decimal)
    for bid, applied in db.execute(select(pa.c.bill_id, pa.c.applied)):
        paid[bid] += dec(applied or 0)
    out = []
    for r in db.execute(select(sb, v.c.name.label("vendor_name"), v.c.msme, v.c.credit_days)
                        .join(v, v.c.id == sb.c.vendor_id, isouter=True).order_by(sb.c.date, sb.c.id)):
        balance = M.money(dec(r.amount or 0) - paid[r.id])
        if balance <= 0:
            continue
        due = M.supplier_due_date(r.date, int(r.credit_days or 30), bool(r.msme), int(msme_days))
        out.append({"id": r.id, "vendor_id": r.vendor_id, "vendor_name": r.vendor_name or "", "bill_no": r.bill_no,
                    "msme": bool(r.msme), "due": due, "balance": balance})
    return out


def _between(iso: str | None, first: date, last: date) -> bool:
    return bool(iso) and first <= date.fromisoformat(iso[:10]) <= last


# ---------------------------------------------------------------- summary

class _Money:
    """Issued invoices, per-job profit and the share of a job's profit an invoice carries."""

    def __init__(self, db: Session):
        self.invoices = invoice_dicts(db)
        self.issued = [i for i in self.invoices if i["status"] != "draft"]
        self.cost = jobs_profit(db)

    def invoice_profit(self, inv: dict) -> Decimal:
        """Job profit x (this invoice's taxable / the job's revenue); 0 for invoices without a job."""
        c = self.cost.get(inv["job_card"] or "")
        if not c or not c["revenue"]:
            return ZERO
        return dec(c["profit"]) * dec(inv["taxable"]) / dec(c["revenue"])

    def window(self, first: date, last: date) -> tuple[Decimal, Decimal, list[dict]]:
        rows = [i for i in self.issued if _between(i["date"], first, last)]
        revenue = sum((dec(i["taxable"]) for i in rows), ZERO)
        profit = sum((self.invoice_profit(i) for i in rows), ZERO)
        return M.money(revenue), M.money(profit), rows


def _trend(m: _Money, period: str, first: date, last: date) -> list[dict]:
    points: list[tuple[str, date, date]] = []
    if period == "today":
        for k in range(6, -1, -1):
            d = last - timedelta(days=k)
            points.append((f"{d.day} {d:%b}", d, d))
    elif period == "month":
        start = first
        n = 1
        while start <= last:
            end = min(start + timedelta(days=6), last)
            points.append((f"W{n} ({start.day}-{end.day})", start, end))
            start, n = end + timedelta(days=1), n + 1
    else:
        start = first
        while start <= last:
            nxt = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
            points.append((f"{start:%b}", start, min(nxt - timedelta(days=1), last)))
            start = nxt
    out = []
    for label, a, b in points:
        rev, prof, _rows = m.window(a, b)
        out.append({"label": label, "revenue": float(rev), "profit": float(prof)})
    return out


def _trend_30d(m: _Money, last: date) -> list[dict]:
    out = []
    for k in range(29, -1, -1):
        d = last - timedelta(days=k)
        rev, prof, _rows = m.window(d, d)
        out.append({"date": d.isoformat(), "label": f"{d.day} {d:%b}", "revenue": float(rev), "profit": float(prof)})
    return out


def _machines(db: Session, runs: list[dict], first: date, last: date) -> list[dict]:
    """Every machine (none capped): output, hours, wastage and month OEE for presses."""
    mc = T("machines")
    oee_by = {m["machine_id"]: m["oee"] for m in prod.oee(db, last.strftime("%Y-%m"))["machines"]}
    mine: dict[str, list[dict]] = defaultdict(list)
    for r in runs:
        if _between(r["start"], first, last):
            mine[r["machine_id"]].append(r)
    out = []
    for m in db.execute(select(mc).order_by(mc.c.id)):
        rs_ = mine.get(m.id, [])
        press = prod.is_press(m.type)
        out.append({
            "machine_id": m.id, "machine_name": m.name or "", "type": P.PRESS if press else "offline",
            "runs": len(rs_),
            "printed_qty": P.printed_total_press_only(rs_) if press else sum(int(r["printed_qty"]) for r in rs_),
            "run_hours": round(float(sum((dec(r["hours"] or 0) for r in rs_), Decimal(0))), 2),
            "wastage_pct": wastage_pct(rs_) if press else 0.0,
            "oee": oee_by.get(m.id) if press else None,
            "running": any(r["status"] == "running" for r in rs_),
        })
    return out


def _oee(db: Session, period: str, first: date, last: date) -> float:
    if period != "year":
        return prod.oee(db, last.strftime("%Y-%m"))["plant_oee"]
    values = []
    start = first
    while start <= last:
        o = prod.oee(db, start.strftime("%Y-%m"))
        if any(m["run_hours"] > 0 for m in o["machines"]):
            values.append(dec(o["plant_oee"]))
        start = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    return _frac(sum(values, Decimal(0)) / len(values)) if values else 0.0


def summary(db: Session, period: str) -> dict:
    first, last = period_bounds(db, period)
    m = _Money(db)
    revenue, profit, inv_rows = m.window(first, last)

    jobs = jobs_svc.list_jobs(db, with_flags=False)
    booked = [j for j in jobs if _between(j["created_on"], first, last)]
    booked_value = M.money(sum((dec(j["po_value"]) for j in booked), ZERO))

    runs = prod.list_runs(db)
    in_period = [r for r in runs if _between(r["start"], first, last)]
    # wastage and crew cost belong to the day a run ended (a night shift ends the next morning)
    ended = [r for r in runs if r["status"] == "ended" and _between(r["end"], first, last)]

    rcp, pay = T("receipts"), T("payments")
    cash_in = sum((dec(a or 0) for (a,) in db.execute(select(rcp.c.amount)
                  .where(rcp.c.date >= first, rcp.c.date <= last))), ZERO)
    paid_out = sum((dec(a or 0) for (a,) in db.execute(select(pay.c.amount)
                   .where(pay.c.date >= first, pay.c.date <= last))), ZERO)
    salaries = sum((dec(r["crew_cost"]) for r in ended if r["crew_cost"] is not None), ZERO)

    open_inv = [i for i in m.issued if i["outstanding"] > 0]
    locks = client_locks(db)
    at_risk = [lk for lk in locks.values() if lk["lock_status"] == "at_risk"]
    horizon = today() + timedelta(days=7)
    due_7d = sum((b["balance"] for b in payables(db) if b["due"] <= horizon), ZERO)
    stock_value = sum((dec(r["value"]) for r in store_svc.stock_rows(db)), ZERO)

    status_count: dict[str, int] = defaultdict(int)
    for j in jobs:
        if j["status"] != "closed":
            status_count[j["status"]] += 1

    names = {i["client_id"]: i["client_name"] for i in m.invoices}
    by_client: dict[str, Decimal] = defaultdict(Decimal)
    by_job: dict[str, Decimal] = defaultdict(Decimal)
    for i in inv_rows:
        by_client[i["client_id"]] += dec(i["taxable"])
        if i["job_card"]:
            by_job[i["job_card"]] += dec(i["taxable"])
    ranked = sorted(by_client.items(), key=lambda kv: (-kv[1], kv[0]))
    client_rows = [{"client_id": cid, "client_name": names.get(cid) or cid, "revenue": float(M.money(v))}
                   for cid, v in ranked]
    job_names = {j["job_card"]: j for j in jobs}
    job_rows = []
    for jc in by_job:
        c = m.cost.get(jc)
        if c is None:
            continue
        j = job_names.get(jc, {})
        job_rows.append({"job_card": jc, "client_name": j.get("client_name", ""), "product": j.get("product", ""),
                         "revenue": c["revenue"], "profit": c["profit"], "margin_pct": c["margin_pct"],
                         "link": f"/jobs/{jc}"})
    job_rows.sort(key=lambda r: (-r["profit"], r["job_card"]))

    return {
        "period": period,
        "from": first.isoformat(),
        "to": last.isoformat(),
        "revenue": float(revenue),
        "invoices_count": len(inv_rows),
        "orders_booked_value": float(booked_value),
        "orders_booked_count": len(booked),
        "printed_qty": P.printed_total_press_only(in_period),
        "wastage_pct": _frac(wastage_pct(ended)),
        "gross_profit": float(profit),
        "margin_pct": _frac(ratio(profit, revenue)) if revenue else 0.0,
        "cash_in": _money(cash_in),
        "cash_out": _money(paid_out + salaries),
        "receivables": _money(sum((dec(i["outstanding"]) for i in open_inv), ZERO)),
        "overdue": _money(sum((dec(i["outstanding"]) for i in open_inv if i["days_past_due"] > 0), ZERO)),
        "at_risk_value": _money(sum((dec(lk["overdue_amount"]) for lk in at_risk), ZERO)),
        "at_risk_clients": len(at_risk),
        "locked_clients": sum(1 for lk in locks.values() if lk["lock_status"] == "locked"),
        "payables_due_7d": _money(due_7d),
        "stock_value": _money(stock_value),
        "oee": _oee(db, period, first, last),
        "jobs_by_status": dict(sorted(status_count.items())),
        "trend": _trend(m, period, first, last),
        "top_clients": client_rows[:TOP_N],
        # additive (not in the contract's required list)
        "bottom_clients": list(reversed(client_rows[-TOP_N:])) if len(client_rows) > TOP_N else [],
        "top_jobs": job_rows[:TOP_N],
        "bottom_jobs": list(reversed(job_rows[-TOP_N:])) if len(job_rows) > TOP_N else [],
        "trend_30d": _trend_30d(m, last),
        "machines": _machines(db, runs, first, last),
    }


# ---------------------------------------------------------------- alerts

# Which roles see which alert areas (owner sees everything).
AREA_ROLES = {
    "money": {"accounts", "marketing"},
    "production": {"production", "ppic", "qc"},
    "store": {"store", "ppic"},
    "qc": {"qc", "production", "dispatch"},
    "dispatch": {"dispatch", "accounts", "ppic"},
    "planning": {"ppic", "store", "production"},
    "design": {"design", "ppic"},
    "agents": set(),
}
_SEV = {"high": 0, "medium": 1, "low": 2}


def _stamp(d: date | str, hour: int = 7, minute: int = 0) -> str:
    if isinstance(d, str):
        d = date.fromisoformat(d[:10])
    return datetime.combine(d, time(hour, minute), IST).isoformat()


def alerts(db: Session, role: str) -> dict:
    t = today()
    s = load_settings(db)
    wtol = float(s.get("wastage_tol") or DEFAULTS.wastage_tol)
    mtol = float(s.get("material_tol") or DEFAULTS.material_tol)
    out: list[dict] = []

    def add(key: str, severity: str, area: str, title: str, detail: str, link: str, created: str) -> None:
        out.append({"id": f"AL-{key}", "severity": severity, "area": area, "title": title, "detail": detail,
                    "link": link, "created_at": created})

    # money: locked clients, clients about to lock
    locks = client_locks(db)
    cl = T("clients")
    names = {cid: n for cid, n in db.execute(select(cl.c.id, cl.c.name))}
    for cid, lk in sorted(locks.items()):
        if lk["lock_status"] == "locked":
            add(f"LOCK-{cid}", "high", "money", f"{names.get(cid, cid)} is LOCKED",
                f"{rs(lk['outstanding'])} unpaid; {lk['reason']}. Dispatch and new jobs blocked.",
                f"/money?tab=debtors&client={cid}", _stamp(lk["locked_since"] or t, 0, 5))
    soon = sorted((lk for lk in locks.values() if lk["lock_status"] == "at_risk" and lk["locks_on"]
                   and date.fromisoformat(lk["locks_on"]) <= t + timedelta(days=10)), key=lambda x: x["locks_on"])
    if soon:
        value = sum((dec(lk["overdue_amount"]) for lk in soon), ZERO)
        add("LOCK-SOON", "high", "money", f"{len(soon)} client{'s' if len(soon) > 1 else ''} lock within 10 days "
            f"({rs(value)})", ", ".join(f"{names.get(lk['client_id'], lk['client_id'])} locks "
                                       f"{day_label(lk['locks_on'])}" for lk in soon) + ".",
            "/money?tab=debtors&filter=at_risk", _stamp(t))

    # money: supplier bills (MSME due soon, overdue)
    for b in payables(db):
        days = (b["due"] - t).days
        link = f"/money?tab=creditors&vendor={b['vendor_id']}"
        if b["msme"] and 0 <= days <= 7:
            add(f"MSME-{b['id']}", "medium", "money", f"MSME bill due in {days} day{'s' if days != 1 else ''}",
                f"{b['vendor_name']} {b['bill_no']} {rs(b['balance'])} due {day_label(b['due'].isoformat())} "
                f"(MSME limit).", link, _stamp(t))
        elif days < 0:
            add(f"BILL-{b['id']}", "high" if b["msme"] else "medium", "money",
                f"{b['vendor_name']} bill overdue {-days} day{'s' if days != -1 else ''}",
                f"{b['bill_no']} {rs(b['balance'])} was due {day_label(b['due'].isoformat())}"
                f"{' (MSME: interest risk)' if b['msme'] else ''}.", link, _stamp(b["due"] + timedelta(days=1)))

    # production: wastage above tolerance in the last 7 days
    runs = prod.list_runs(db)
    since = t - timedelta(days=7)
    for r in sorted(runs, key=lambda x: x["start"]):
        if r["wastage_flag"] and _day(r["start"]) >= since:
            stops = ", ".join(f"{x['reason']} {x['minutes']} min" for x in r["stops"]) or "no stops logged"
            add(f"WST-{r['id']}", "high", "production",
                f"{r['job_card']} wastage {pct(r['wastage_pct'])} (limit {wtol * 100:.0f}%)",
                f"{r['machine_name']} {r['shift']} shift {day_label(r['start'][:10])}: {num(r['wastage_m'], 2)} m "
                f"wasted of {num(r['required_m'], 2)} m required; {stops}.", f"/jobs/{r['job_card']}",
                r["end"] or r["start"])

    # jobs: material variance, QC hold, late
    jobs = jobs_svc.list_jobs(db)
    for j in jobs:
        jc, flags = j["job_card"], j["flags"]
        if "material_variance" in flags and j["status"] not in jobs_svc.DONE:
            var = float(ratio(dec(j["issued_m"]) - dec(j["planned_m"]), j["planned_m"])) if j["planned_m"] else 0.0
            add(f"MAT-{jc}", "medium", "store", f"{jc} material issued {pct(var)} vs plan (limit {mtol * 100:.0f}%)",
                f"Issued {num(j['issued_m'], 2)} m vs planned {num(j['planned_m'], 2)} m of {j['material']}.",
                f"/jobs/{jc}", _stamp(t))
        if "qc_hold" in flags:
            held = [q for q in db.execute(select(T("qc")).where(T("qc").c.job_card == jc)).all()
                    if str(q.decision or "").lower() == "hold"]
            qty = sum(int(q.checked or 0) for q in held)
            add(f"QCH-{jc}", "medium", "qc", f"{jc}: {num(qty)} labels on QC Hold",
                f"{j['client_name']} {j['product']}: not available for dispatch until released.",
                f"/qc?job={jc}", _stamp(max((q.date for q in held), default=t), 17, 40))
        if "late" in flags:
            add(f"LATE-{jc}", "medium", "dispatch", f"{jc} is late (due {day_label(j['due_date'])})",
                f"{j['client_name']}: {num(j['dispatched_qty'])} of {num(j['order_qty'])} dispatched; status "
                f"{j['status']}.", f"/jobs/{jc}", _stamp(t))

    # planning: paper shortages for open jobs
    for it in jobs_svc.material_summary(db, jobs)["items"]:
        if it["status"] == "short":
            cards = " and ".join(x["job_card"] for x in it["jobs"])
            add(f"SHORT-{it['item_id']}", "medium", "planning", f"{it['material']} short by {num(it['shortage_m'], 2)} m",
                f"{cards} need {num(it['need_m'], 2)} m; stock {num(it['stock_m'], 2)} m.",
                "/jobs?flag=material_short", _stamp(t))

    # store: GRN rate flags (last 30 days), issues without a job card
    for g in store_svc.list_grns(db, since=t - timedelta(days=30)):
        if g["rate_flag"]:
            add(f"GRN-{g['id']}", "medium", "store", f"{g['id']} rate {pct(abs(g['rate_diff_pct']))} "
                f"{'above' if g['rate_diff_pct'] > 0 else 'below'} master",
                f"{g['item_name']} billed at Rs {g['rate']:.2f} vs Rs {g['item_rate']:.2f} ({g['vendor_name']}).",
                f"/store?tab=grns&id={g['id']}", _stamp(g["date"], 15, 20))
    iss = T("issues")
    total = missing = 0
    missing_value = ZERO
    items = store_svc.items_by_id(db)
    for jc, iid, qty in db.execute(select(iss.c.job_card, iss.c.item_id, iss.c.qty)):
        total += 1
        if not jc:
            missing += 1
            missing_value += store_svc.line_value(qty, items.get(iid))
    if missing:
        add("DQ-NOJC", "low", "store", f"{pct(ratio(missing, total))} of issue lines have no job card",
            f"{num(missing)} of {num(total)} issue lines worth {rs(missing_value)} (ink and varnish go to the "
            f"monthly ink pool).", "/store?tab=data-quality", _stamp(t))

    if role != "owner":
        out = [a for a in out if role in AREA_ROLES.get(a["area"], set())]
    out.sort(key=lambda a: a["created_at"], reverse=True)  # newest first within a severity
    out.sort(key=lambda a: _SEV[a["severity"]])
    return {"as_of": now().isoformat(), "alerts": out}


# ---------------------------------------------------------------- floor board

def _shift(at: datetime) -> str:
    return "day" if time(7, 0) <= at.time() < time(19, 0) else "night"


def floor_board(db: Session) -> dict:
    t = today()
    at = prod.plant_now()
    shift = _shift(at)
    runs = prod.list_runs(db)
    raw = {r.id: r for r in prod._run_rows(db, T("runs").c.end.is_(None))}
    jobs = {j["job_card"]: j for j in jobs_svc.list_jobs(db)}
    ps = T("press_setup")
    speeds = {(jc, mid): sp for jc, mid, sp in db.execute(select(ps.c.job_card, ps.c.machine_id,
                                                                 ps.c.speed_target_mpm))}
    oee_by = {m["machine_id"]: m["oee"] for m in prod.oee(db, t.strftime("%Y-%m"))["machines"]}
    order = {"high": 0, "normal": 1, "low": 2}
    queue_status = ("planned", "design", "printing")
    mc = T("machines")
    machines = []
    for m in db.execute(select(mc).order_by(mc.c.id)):
        running = next((r for r in runs if r["machine_id"] == m.id and r["status"] == "running"), None)
        today_runs = [r for r in runs if r["machine_id"] == m.id and _day(r["start"]) == t]
        current = running["job_card"] if running else None
        queue = sorted((j for j in jobs.values() if j["machine_id"] == m.id and j["status"] in queue_status
                        and j["job_card"] != current),
                       key=lambda j: (order.get(j["priority"], 1), j["due_date"] or "9999", j["job_card"]))
        nxt = queue[0] if queue else None
        row = {"machine_id": m.id, "machine_name": m.name or "", "status": "idle", "stop_reason": None,
               "run_id": None, "job_card": None, "client_name": None, "product": None, "counter": 0, "target": 0,
               "progress_pct": 0.0, "speed_mpm": 0.0, "metres_run": 0.0, "operator": None, "shift": shift,
               "started_at": None, "eta": None, "next_job_card": nxt["job_card"] if nxt else None, "alert": None}
        alert = None
        if running:
            job = jobs.get(current, {})
            seed = prod.counter_seed(raw[running["id"]], speeds.get((current, m.id)))
            target = int(job.get("order_qty") or 0)
            stops = running["stops"]
            stopped = bool(stops)  # demo: a stop logged on a running run is the current stop
            speed = 0.0 if stopped else round(seed["speed"], 1)
            eta = None
            if target and seed["ups"] and seed["repeat_mm"] and seed["speed"]:
                left_m = max(target - seed["count"], 0) / seed["ups"] * seed["repeat_mm"] / 1000
                eta = (datetime.combine(t, at.time(), IST) + timedelta(minutes=left_m / seed["speed"])) \
                    .replace(microsecond=0).isoformat()
            row.update({"status": "stopped" if stopped else "running",
                        "stop_reason": stops[-1]["reason"] if stopped else None, "run_id": running["id"],
                        "job_card": current, "client_name": running["client_name"] or None,
                        "product": job.get("product") or None, "counter": seed["count"], "target": target,
                        "progress_pct": _frac(ratio(seed["count"], target)) if target else 0.0,
                        "speed_mpm": speed, "metres_run": round(seed["metres"], 2),
                        "operator": running["operator"] or None, "shift": running["shift"],
                        "started_at": running["start"], "eta": eta})
            if stopped:
                alert = f"Stopped {stops[-1]['minutes']} min"
        if alert is None and nxt and "material_short" in nxt["flags"]:
            alert = f"Next job short of {nxt['material']}"
        if alert is None and current and "wastage_high" in jobs.get(current, {}).get("flags", []):
            alert = "Wastage above limit"
        row["alert"] = alert
        press = prod.is_press(m.type)
        row.update({  # additive per-machine fields
            "type": P.PRESS if press else "offline",
            "today_printed_qty": P.printed_total_press_only(today_runs) if press
            else sum(int(r["printed_qty"]) for r in today_runs),
            "today_wastage_pct": _frac(wastage_pct([r for r in today_runs if r["status"] == "ended"])),
            "oee": oee_by.get(m.id) if press else None,
            "queue": [j["job_card"] for j in queue],
        })
        machines.append(row)
    machines.sort(key=lambda r: (r["type"] != P.PRESS, r["machine_id"]))

    today_press = [r for r in runs if _day(r["start"]) == t]
    ended_today = [r for r in runs if r["status"] == "ended" and r["end"] and _day(r["end"]) == t
                   and r["machine_type"] == P.PRESS]
    printed = P.printed_total_press_only(today_press)
    ticker = []
    for r in ended_today:
        if r["wastage_flag"]:
            ticker.append(f"{r['job_card']} {r['shift']} wastage {pct(r['wastage_pct'])} - check plates before repeat")
    ticker.append(f"Printed today so far: {num(printed)} labels")
    for j in sorted(jobs.values(), key=lambda j: j["due_date"] or "9999"):
        if j["status"] in ("printing", "qc", "dispatch") and j["due_date"] and \
                date.fromisoformat(j["due_date"]) <= t + timedelta(days=3):
            ticker.append(f"{j['job_card']} ({j['client_name']}) due {day_label(j['due_date'])}")
    ticker.append("Safety first: guards on before threading")
    return {
        "as_of": now().isoformat(),
        "shift": shift,
        "machines": machines,
        "today": {"printed_qty": printed, "jobs_done": len({r["job_card"] for r in ended_today}),
                  "wastage_pct": _frac(wastage_pct(ended_today))},
        "ticker": ticker,
    }
