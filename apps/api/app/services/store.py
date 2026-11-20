"""Store: live stock, GRNs, issues, rolls, slitting, party laminate, ink pool, data quality (SPEC 2 and 3).

All stock, UOM, rate-check, trim and ink maths goes through ``core.rules``; stock balances come
from :func:`app.services.jobs.stock_by_item` so the Store screen and the PPIC material summary
always show the same number. This module only gathers rows and shapes contract JSON
(``StoreSummary``, ``StockResponse``, ``Grn``, ``Issue``, ``Roll``, ``Slitting``, ... in
contract/openapi.yaml).
"""
from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.deps import T, today
from app.routers.shell import load_settings
from app.services.jobs import material_summary, stock_by_item, tolerances
from core.rules import store as S
from core.rules.dates import parse_erp_date
from core.rules.errors import RuleError, dec, money, ratio
from core.rules.settings import DEFAULTS

# An item with stock but no receipt/issue for this many days is "non_moving" (StockRow.status).
NON_MOVING_DAYS = 45
INK_GROUPS = ("Ink", "Varnish")  # issued without a job card -> monthly ink pool (SPEC 2)
ROLL_UOM = "m"  # items kept in numbered rolls (paper, film, foil, lamination)
MONTH_RE = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")
_DATE_TEXT_ISO = re.compile(r"^\s*\d{4}-")


# ---------------------------------------------------------------- small helpers

def _f(v: Any, places: int = 3) -> float:
    return round(float(v or 0), places)


def _iso(v: Any) -> str | None:
    return v.isoformat() if isinstance(v, date) else v


def store_tolerances(db: Session) -> dict[str, Any]:
    """jobs.tolerances (stock_from, planning...) plus the store ones (grn_rate_tol, slit_tol, ink_tol)."""
    tol = tolerances(db)
    s = load_settings(db)
    for key in ("grn_rate_tol", "slit_tol", "ink_tol"):
        v = s.get(key)
        tol[key] = float(v) if v is not None else getattr(DEFAULTS, key)
    return tol


def month_bounds(month: str) -> tuple[date, date]:
    """``YYYY-MM`` -> (first day, last day). RuleError when malformed."""
    m = MONTH_RE.match(month or "")
    if not m:
        raise RuleError(f"invalid month '{month}' (expected YYYY-MM)")
    first = date(int(m.group(1)), int(m.group(2)), 1)
    nxt = date(first.year + (first.month == 12), first.month % 12 + 1, 1)
    return first, nxt - timedelta(days=1)


def items_by_id(db: Session, ids: Iterable[str] | None = None) -> dict[str, Any]:
    t = T("items")
    stmt = select(t)
    if ids is not None:
        stmt = stmt.where(t.c.id.in_(set(ids)))
    return {r.id: r for r in db.execute(stmt.order_by(t.c.id))}


def is_sqm_item(item: Any) -> bool:
    """Metres of a per-sq-m roll item convert to sq m (StockRow.stock_sqm / Issue.sqm)."""
    return bool(item is not None and (item.uom or "") == ROLL_UOM and item.width_mm
                and (item.rate_unit or "") == "per_sqm")


def sqm_of(qty: Any, item: Any) -> float | None:
    """sq m = metres * width_mm / 1000 (core.rules.store.metres_to_sqm), None for non-sq-m items."""
    if not is_sqm_item(item):
        return None
    return S.metres_to_sqm(qty or 0, item.width_mm)


def line_value(qty: Any, item: Any, rate: Any = None) -> Decimal:
    """Value of ``qty`` of an item: sq m * rate for per-sq-m roll items, else qty * rate (schema.md)."""
    r = dec(rate if rate is not None else ((item.rate if item is not None else 0) or 0))
    sqm = sqm_of(qty, item)
    base = dec(sqm) if sqm is not None else dec(qty or 0)
    return money(base * r)


def _group(item: Any) -> str:
    return (item.group if item is not None else None) or "Other"


def _names(db: Session, table: str, ids: Iterable[str]) -> dict[str, str]:
    t = T(table)
    ids = {i for i in ids if i}
    if not ids:
        return {}
    return {r.id: r.name for r in db.execute(select(t.c.id, t.c.name).where(t.c.id.in_(ids)))}


# ---------------------------------------------------------------- stock

def _movements(db: Session, stock_from: date | None) -> tuple[dict, dict, dict, dict]:
    """(opening, received, issued, last_movement) per item, with the same filters as stock_by_item."""
    op, grns, issues = T("opening_stock"), T("grns"), T("issues")
    opening: dict[str, Decimal] = defaultdict(Decimal)
    last: dict[str, date] = {}
    for iid, qty, as_of in db.execute(select(op.c.item_id, op.c.qty, op.c.as_of)):
        if stock_from is None or as_of is None or as_of == stock_from:
            opening[iid] += dec(qty or 0)
            if as_of is not None:
                last[iid] = max(last.get(iid, as_of), as_of)

    def sums(t) -> dict[str, Decimal]:
        out: dict[str, Decimal] = defaultdict(Decimal)
        s = select(t.c.item_id, func.sum(t.c.qty), func.max(t.c.date)).group_by(t.c.item_id)
        if stock_from is not None:
            s = s.where(t.c.date >= stock_from)
        for iid, qty, last_day in db.execute(s):
            out[iid] = dec(qty or 0)
            if last_day is not None:
                last[iid] = max(last.get(iid, last_day), last_day)
        return out

    return opening, sums(grns), sums(issues), last


def stock_rows(db: Session, tol: dict | None = None) -> list[dict]:
    """One contract ``StockRow`` per item master row. ``stock`` comes from jobs.stock_by_item."""
    tol = tol or store_tolerances(db)
    stock_from = tol["stock_from"]
    items = items_by_id(db)
    balances = stock_by_item(db, items, stock_from)
    opening, received, issued, last = _movements(db, stock_from)
    as_of = today()
    rows = []
    for iid, it in items.items():
        stock = dec(balances.get(iid, 0))
        min_stock = dec(it.min_stock or 0)
        last_day = last.get(iid) or stock_from or as_of
        if stock <= 0 and (min_stock > 0 or stock < 0):
            status = "short"
        elif stock < min_stock:
            status = "low"
        elif stock > 0 and (as_of - last_day).days > NON_MOVING_DAYS:
            status = "non_moving"
        else:
            status = "ok"
        sqm = sqm_of(stock, it)
        rows.append({
            "item_id": iid,
            "item_name": it.name or iid,
            "group": _group(it),
            "width_mm": int(it.width_mm) if it.width_mm is not None else None,
            "uom": it.uom or "",
            "opening": _f(opening.get(iid)),
            "received": _f(received.get(iid)),
            "issued": _f(issued.get(iid)),
            "stock": _f(stock),
            "stock_sqm": sqm,
            "rate": float(money(it.rate or 0)),
            "value": float(line_value(stock, it)),
            "min_stock": _f(min_stock),
            "status": status,
            "last_movement": last_day.isoformat(),
        })
    return rows


def stock(db: Session, group: str | None = None, q: str | None = None) -> dict:
    tol = store_tolerances(db)
    rows = stock_rows(db, tol)
    if group:
        g = group.strip().lower()
        known = {r["group"].lower() for r in rows}
        if g not in known:
            raise RuleError(f"unknown group '{group}' (known: {', '.join(sorted({r['group'] for r in rows}))})")
        rows = [r for r in rows if r["group"].lower() == g]
    if q and q.strip():
        needle = q.strip().lower()
        rows = [r for r in rows if needle in r["item_id"].lower() or needle in r["item_name"].lower()]
    total = sum((dec(r["value"]) for r in rows), Decimal(0))
    return {
        "as_of": today().isoformat(),
        "stock_from": _iso(tol["stock_from"]) or today().isoformat(),
        "total_value": float(money(total)),
        "items": rows,
    }


# ---------------------------------------------------------------- GRNs

def _grn_rate_check(rate: Any, item_rate: Any, tol: float) -> tuple[float, bool]:
    flag = S.grn_rate_flag(rate or 0, item_rate or 0, tol)
    diff = float(ratio(dec(rate or 0) - dec(item_rate), item_rate)) if dec(item_rate or 0) != 0 else 0.0
    return diff, flag


def list_grns(db: Session, *, ids: Iterable[str] | None = None, since: date | None = None,
              until: date | None = None, tol: dict | None = None) -> list[dict]:
    """Contract ``Grn`` dicts (rate check against the item master rate), oldest first."""
    tol = tol or store_tolerances(db)
    g, rolls = T("grns"), T("rolls")
    stmt = select(g)
    if ids is not None:
        stmt = stmt.where(g.c.id.in_(set(ids)))
    if since is not None:
        stmt = stmt.where(g.c.date >= since)
    if until is not None:
        stmt = stmt.where(g.c.date <= until)
    rows = db.execute(stmt.order_by(g.c.date, g.c.id)).all()
    items = items_by_id(db, {r.item_id for r in rows})
    vendors = _names(db, "vendors", {r.vendor_id for r in rows})
    roll_ids: dict[str, list[str]] = defaultdict(list)
    if rows:
        for rid, ref in db.execute(select(rolls.c.id, rolls.c.source_ref)
                                   .where(rolls.c.source == "grn", rolls.c.source_ref.in_({r.id for r in rows}))
                                   .order_by(rolls.c.id)):
            roll_ids[ref].append(rid)
    out = []
    for r in rows:
        it = items.get(r.item_id)
        item_rate = (it.rate if it is not None else None) or 0
        diff, flag = _grn_rate_check(r.rate, item_rate, tol["grn_rate_tol"])
        out.append({
            "id": r.id,
            "date": _iso(r.date),
            "vendor_id": r.vendor_id or "",
            "vendor_name": vendors.get(r.vendor_id, "") if r.vendor_id else "",
            "bill_no": r.bill_no or r.ref or "",
            "item_id": r.item_id,
            "item_name": (it.name if it is not None else None) or r.item_id,
            "qty": _f(r.qty),
            "uom": (it.uom if it is not None else None) or "",
            "rate": float(money(r.rate or 0)),
            "item_rate": float(money(item_rate)),
            "rate_diff_pct": diff,
            "rate_flag": flag,
            "amount": float(line_value(r.qty, it, r.rate or 0)),
            "roll_ids": roll_ids.get(r.id, []),
            "is_demo": bool(r.is_demo),
        })
    return out


# ---------------------------------------------------------------- issues

def list_issues(db: Session, *, job_card: str | None = None, missing_jc: bool = False,
                ids: Iterable[str] | None = None, since: date | None = None,
                until: date | None = None) -> list[dict]:
    """Contract ``Issue`` dicts, oldest first. Value = qty (or sq m) * item master rate."""
    t = T("issues")
    stmt = select(t)
    if job_card:
        stmt = stmt.where(t.c.job_card == job_card)
    if missing_jc:
        stmt = stmt.where(t.c.job_card.is_(None))
    if ids is not None:
        stmt = stmt.where(t.c.id.in_(set(ids)))
    if since is not None:
        stmt = stmt.where(t.c.date >= since)
    if until is not None:
        stmt = stmt.where(t.c.date <= until)
    rows = db.execute(stmt.order_by(t.c.date, t.c.id)).all()
    items = items_by_id(db, {r.item_id for r in rows})
    return [issue_dict(r, items.get(r.item_id)) for r in rows]


def issue_dict(r: Any, it: Any) -> dict:
    return {
        "id": r.id,
        "date": _iso(r.date),
        "job_card": r.job_card,
        "item_id": r.item_id,
        "item_name": (it.name if it is not None else None) or r.item_id,
        "qty": _f(r.qty),
        "uom": (it.uom if it is not None else None) or "",
        "sqm": sqm_of(r.qty, it),
        "roll_id": r.roll_id,
        "rate": float(money((it.rate if it is not None else None) or 0)),
        "value": float(line_value(r.qty, it)),
        "issued_to": r.issued_to or "",
        "source": r.source if r.source in ("app", "erp_import") else "app",
        "is_demo": bool(r.is_demo),
    }


# ---------------------------------------------------------------- rolls

def roll_balances(db: Session, roll_ids: Iterable[str] | None = None) -> dict[str, dict]:
    """Per roll: balance = length - issued - slit-out metres (schema.md), plus the job cards issued to."""
    rolls, issues, slit = T("rolls"), T("issues"), T("slitting")
    stmt = select(rolls.c.id, rolls.c.length_m)
    if roll_ids is not None:
        stmt = stmt.where(rolls.c.id.in_(set(roll_ids)))
    out = {rid: {"length": dec(length or 0), "used": [], "jobs": []} for rid, length in db.execute(stmt)}
    if not out:
        return {}
    for rid, qty, jc in db.execute(select(issues.c.roll_id, issues.c.qty, issues.c.job_card)
                                   .where(issues.c.roll_id.in_(set(out)))
                                   .order_by(issues.c.date, issues.c.id)):
        out[rid]["used"].append(qty or 0)
        if jc and jc not in out[rid]["jobs"]:
            out[rid]["jobs"].append(jc)
    for rid, length in db.execute(select(slit.c.jumbo_roll_id, slit.c.length_m)
                                  .where(slit.c.jumbo_roll_id.in_(set(out)))):
        out[rid]["used"].append(length or 0)
    for v in out.values():
        # same formula as stock: opening (roll length) + nothing received - used
        v["balance"] = S.stock_balance(v["length"], [], v["used"])
    return out


def list_rolls(db: Session) -> list[dict]:
    rolls = T("rolls")
    rows = db.execute(select(rolls).order_by(rolls.c.received_on, rolls.c.id)).all()
    items = items_by_id(db, {r.item_id for r in rows})
    bal = roll_balances(db)
    out = []
    for r in rows:
        b = bal.get(r.id) or {"balance": dec(r.length_m or 0), "jobs": [], "used": []}
        balance = b["balance"]
        status = "consumed" if balance <= 0 else ("partly_issued" if b["used"] else "in_stock")
        it = items.get(r.item_id)
        out.append({
            "id": r.id,
            "item_id": r.item_id,
            "item_name": (it.name if it is not None else None) or r.item_id,
            "width_mm": int(r.width_mm or (it.width_mm if it is not None else 0) or 0),
            "length_m": _f(r.length_m),
            "balance_m": _f(max(balance, Decimal(0))),
            "source": r.source if r.source in ("grn", "slit", "opening") else "opening",
            "source_ref": r.source_ref or "",
            "received_on": _iso(r.received_on) or "",
            "status": status,
            "issued_to": b["jobs"],
            "location": r.location or "",
            "is_demo": bool(r.is_demo),
        })
    return out


# ---------------------------------------------------------------- slitting

def list_slitting(db: Session, tol: dict | None = None) -> list[dict]:
    tol = tol or store_tolerances(db)
    sl, rolls = T("slitting"), T("rolls")
    rows = db.execute(select(sl).order_by(sl.c.date, sl.c.id)).all()
    jumbo_items = {rid: iid for rid, iid in db.execute(
        select(rolls.c.id, rolls.c.item_id).where(rolls.c.id.in_({r.jumbo_roll_id for r in rows})))} if rows else {}
    items = items_by_id(db, set(jumbo_items.values()))
    out = []
    for r in rows:
        outputs = []
        widths: list[int] = []
        for o in r.outputs or []:
            w, n = int(o.get("width_mm") or 0), int(o.get("count") or 0)
            ids = list(o.get("roll_ids") or [])
            outputs.append({"width_mm": w, "count": n, "roll_ids": ids})
            widths += [w] * n
        jumbo = int(r.jumbo_width_mm or 0)
        used = sum(widths)
        trim = max(jumbo - used, 0)
        try:
            pct = S.slit_trim_pct(jumbo, widths)
            flag = S.slit_trim_flag(jumbo, widths, tol["slit_tol"])
        except RuleError:  # bad row (no width / slits wider than the jumbo): show, do not flag
            pct, flag = 0.0, False
        it = items.get(jumbo_items.get(r.jumbo_roll_id))
        trim_value = Decimal("0.00")
        if trim > 0 and it is not None:
            trim_sqm = S.metres_to_sqm(r.length_m or 0, trim)
            trim_value = money(dec(trim_sqm) * dec(it.rate or 0))
        out.append({
            "id": r.id,
            "date": _iso(r.date),
            "jumbo_roll_id": r.jumbo_roll_id,
            "item_name": (it.name if it is not None else None) or r.jumbo_roll_id,
            "jumbo_width_mm": jumbo,
            "length_m": _f(r.length_m),
            "outputs": outputs,
            "used_width_mm": used,
            "trim_mm": trim,
            "trim_pct": pct,
            "trim_flag": flag,
            "trim_value": float(trim_value),
            "operator": r.operator or "",
            "is_demo": bool(r.is_demo),
        })
    return out


# ---------------------------------------------------------------- party laminate

def party_laminate(db: Session) -> dict:
    """Customer-owned laminate (ABL/PBL): its own ledger, never part of our stock value."""
    pl = T("party_laminate")
    rows = db.execute(select(pl).order_by(pl.c.date, pl.c.id)).all()
    clients = _names(db, "clients", {r.client_id for r in rows})
    running: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
    out = []
    for r in rows:
        key = (r.client_id, r.laminate or "")
        moved = [r.qty_m or 0]
        if r.movement == "in":
            running[key] = S.stock_balance(running[key], moved, [])
        else:
            running[key] = S.stock_balance(running[key], [], moved)
        out.append({
            "id": r.id,
            "date": _iso(r.date),
            "client_id": r.client_id,
            "client_name": clients.get(r.client_id, r.client_id),
            "movement": "in" if r.movement == "in" else "out",
            "laminate": r.laminate or "",
            "width_mm": int(r.width_mm or 0),
            "qty_m": _f(r.qty_m),
            "job_card": r.job_card,
            "balance_m": _f(running[key]),
            "is_demo": bool(r.is_demo),
        })
    balances = [{"client_id": cid, "client_name": clients.get(cid, cid), "laminate": lam, "balance_m": _f(v)}
                for (cid, lam), v in sorted(running.items())]
    return {"as_of": today().isoformat(), "balances": balances, "rows": out}


# ---------------------------------------------------------------- ink pool

def ink_allocation(db: Session, month: str) -> dict:
    """Ink/varnish issued without a job card in ``month``, shared to that month's press jobs in
    proportion to their estimated ink (core.rules.store.ink_pool_allocation)."""
    first, last = month_bounds(month)
    s = load_settings(db)
    ink_tol = float(s["ink_tol"]) if s.get("ink_tol") is not None else DEFAULTS.ink_tol
    issues, runs, machines, ps, jobs, clients = (T("issues"), T("runs"), T("machines"), T("press_setup"),
                                                 T("jobs"), T("clients"))
    items = items_by_id(db)
    ink_items = {iid for iid, it in items.items() if (it.group or "") in INK_GROUPS}
    pool = Decimal(0)
    for iid, qty in db.execute(select(issues.c.item_id, issues.c.qty)
                               .where(issues.c.job_card.is_(None), issues.c.date >= first, issues.c.date <= last)):
        if iid in ink_items:
            pool += line_value(qty, items[iid])
    pool = money(pool)

    # jobs printed on a press this month, in order of their first run
    first_run: dict[str, Any] = {}
    stmt = (select(runs.c.job_card, func.min(runs.c.start))
            .join(machines, machines.c.id == runs.c.machine_id)
            .where(func.lower(machines.c.type) == "press",
                   func.date(runs.c.start) >= first.isoformat(), func.date(runs.c.start) <= last.isoformat())
            .group_by(runs.c.job_card))
    for jc, start in db.execute(stmt):
        first_run[jc] = start
    est: dict[str, Decimal] = defaultdict(Decimal)
    if first_run:
        for jc, kg in db.execute(select(ps.c.job_card, ps.c.est_ink_kg).where(ps.c.job_card.in_(set(first_run)))):
            est[jc] += dec(kg or 0)
    order = sorted((jc for jc in first_run if est.get(jc, 0) > 0), key=lambda j: (str(first_run[j]), j))
    estimates = {jc: est[jc] for jc in order}
    shares = S.ink_pool_allocation(pool, estimates) if estimates else {}
    total_kg = sum(estimates.values(), Decimal(0))
    names = {}
    if order:
        names = {jc: name for jc, name in db.execute(
            select(jobs.c.job_card, clients.c.name).join(clients, clients.c.id == jobs.c.client_id, isouter=True)
            .where(jobs.c.job_card.in_(set(order))))}
    ink_rates = [dec(it.rate) for iid, it in items.items() if (it.group or "") == "Ink" and it.rate]
    ink_rate = sum(ink_rates, Decimal(0)) / len(ink_rates) if ink_rates else Decimal(0)
    estimate_value = money(total_kg * ink_rate)
    variance = float(ratio(pool - estimate_value, estimate_value)) if estimate_value else 0.0
    rows = [{
        "job_card": jc,
        "client_name": names.get(jc) or "",
        "est_ink_kg": _f(estimates[jc]),
        "share_pct": float(ratio(estimates[jc], total_kg)) if total_kg else 0.0,
        "allocated_value": float(shares.get(jc, Decimal(0))),
    } for jc in order]
    return {
        "month": month,
        "pool_value": float(pool),
        "estimate_value": float(estimate_value),
        "variance_pct": variance,
        "ink_flag": S.ink_flag(pool, estimate_value, ink_tol),
        "rows": rows,
    }


# ---------------------------------------------------------------- summary

def summary(db: Session) -> dict:
    tol = store_tolerances(db)
    as_of = today()
    month = as_of.strftime("%Y-%m")
    first, last = month_bounds(month)
    rows = stock_rows(db, tol)
    group_order: list[str] = []
    groups: dict[str, dict[str, Decimal]] = {}

    def grp(name: str) -> dict[str, Decimal]:
        if name not in groups:
            group_order.append(name)
            groups[name] = defaultdict(Decimal)
        return groups[name]

    for r in rows:
        grp(r["group"])["stock_value"] += dec(r["value"])
    items = items_by_id(db)
    grns = list_grns(db, since=first, until=last, tol=tol)
    for g in grns:
        grp(_group(items.get(g["item_id"])))["received_value_month"] += dec(g["amount"])
    issues = list_issues(db, since=first, until=last)
    for i in issues:
        bucket = grp(_group(items.get(i["item_id"])))
        bucket["issued_value_month"] += dec(i["value"])
        if not i["job_card"]:
            bucket["issued_without_jc_value_month"] += dec(i["value"])
    no_jc = sum(1 for i in issues if not i["job_card"])
    shortages = [it for it in material_summary(db, tol=tol)["items"] if it["status"] == "short"]
    return {
        "as_of": as_of.isoformat(),
        "stock_from": _iso(tol["stock_from"]) or as_of.isoformat(),
        "month": month,
        "stock_value": float(money(sum((dec(r["value"]) for r in rows), Decimal(0)))),
        "groups": [{
            "group": name,
            "stock_value": float(money(groups[name]["stock_value"])),
            "received_value_month": float(money(groups[name]["received_value_month"])),
            "issued_value_month": float(money(groups[name]["issued_value_month"])),
            "issued_without_jc_value_month": float(money(groups[name]["issued_without_jc_value_month"])),
        } for name in group_order],
        "grns_month": len(grns),
        "issues_month": len(issues),
        "issue_lines_without_jc_pct": float(ratio(no_jc, len(issues))) if issues else 0.0,
        "below_min": sum(1 for r in rows if r["status"] in ("low", "short")),
        "shortages": shortages,
        "rate_flags": sum(1 for g in grns if g["rate_flag"]),
        "non_moving_items": sum(1 for r in rows if r["status"] == "non_moving"),
    }


# ---------------------------------------------------------------- data quality

def _date_fix(raw: str | None, stored: date | None) -> tuple[date, date | None] | None:
    """(fixed_to, excel_read_as) when an ERP ``dd-mm-yy`` text is read day first and Excel would
    have read it differently (month first, or not as a date at all when the day is > 12)."""
    if not raw or not str(raw).strip() or _DATE_TEXT_ISO.match(str(raw)):
        return None
    try:
        fixed = parse_erp_date(stored, raw_text=raw)
    except RuleError:
        return None
    if fixed.day == fixed.month:
        return None
    excel = parse_erp_date(fixed, swap_misread=True) if fixed.day <= 12 else None
    return fixed, excel


def _id_number(ident: str) -> int:
    m = re.search(r"(\d+)$", ident or "")
    return int(m.group(1)) if m else 0


def _month_label(d: date) -> str:
    return d.strftime("%b")


def data_quality(db: Session) -> dict:
    """ERP import report: lines without job card, day-first date fixes, unknown job cards, item master gaps.

    Scope: the imported (``erp_import``) issue and GRN lines; with no import loaded, every line.
    """
    tol = store_tolerances(db)
    issues, grns, jobs = T("issues"), T("grns"), T("jobs")
    has_import = db.execute(select(issues.c.id).where(issues.c.source == "erp_import").limit(1)).first() is not None \
        or db.execute(select(grns.c.id).where(grns.c.source == "erp_import").limit(1)).first() is not None
    i_stmt, g_stmt = select(issues), select(grns)
    if has_import:
        i_stmt = i_stmt.where(issues.c.source == "erp_import")
        g_stmt = g_stmt.where(grns.c.source == "erp_import")
    i_rows = db.execute(i_stmt.order_by(issues.c.date, issues.c.id)).all()
    g_rows = db.execute(g_stmt.order_by(grns.c.date, grns.c.id)).all()
    items = items_by_id(db)
    job_cards = {jc for (jc,) in db.execute(select(jobs.c.job_card))}

    dates = [r.date for r in (*i_rows, *g_rows) if r.date is not None]
    period_from = min(dates) if dates else today()
    period_to = max(dates) if dates else today()
    if has_import:
        span = _month_label(period_from) if (period_from.year, period_from.month) == (period_to.year, period_to.month) \
            else f"{_month_label(period_from)}-{_month_label(period_to)}"
        source = f"ERP issue + GRN export ({span} {period_to.year})"
    else:
        source = "App entries (no ERP import loaded)"

    total = len(i_rows)
    no_jc = [r for r in i_rows if not r.job_card]
    value_no_jc = money(sum((line_value(r.qty, items.get(r.item_id)) for r in no_jc), Decimal(0)))
    unknown = [r for r in i_rows if r.job_card and r.job_card not in job_cards]
    value_unknown = money(sum((line_value(r.qty, items.get(r.item_id)) for r in unknown), Decimal(0)))

    fixes = []
    for r in (*i_rows, *g_rows):
        fx = _date_fix(r.raw_date, r.date)
        if fx is not None:
            fixes.append({"source_row": _id_number(r.id), "doc_no": r.ref or r.id, "raw": str(r.raw_date).strip(),
                          "excel_read_as": _iso(fx[1]), "fixed_to": fx[0].isoformat()})
    fixes.sort(key=lambda f: (f["fixed_to"], f["doc_no"]))
    lines = total + len(g_rows)

    rate_flags = 0
    for r in g_rows:
        it = items.get(r.item_id)
        if it is not None and S.grn_rate_flag(r.rate or 0, it.rate or 0, tol["grn_rate_tol"]):
            rate_flags += 1
    no_rate = sum(1 for it in items.values() if not it.rate)
    no_head = sum(1 for it in items.values() if not it.stock_head_id)
    negative = [r for r in stock_rows(db, tol) if r["stock"] < 0]

    def pct(n: int, d: int) -> float | None:
        return float(ratio(n, d)) if d else None

    def sev(n: int, high: bool = False) -> str:
        if n == 0:
            return "low"
        return "high" if high else "medium"

    pct_no_jc = pct(len(no_jc), total)
    checks = [
        {"key": "issue_without_jc", "label": "Issue lines without job card", "count": len(no_jc),
         "pct": pct_no_jc, "value": float(value_no_jc),
         "severity": sev(len(no_jc), high=(pct_no_jc or 0) > 0.05), "link": "/store?tab=issues&jc=missing"},
        {"key": "date_fixes", "label": "Dates fixed to day-first", "count": len(fixes), "pct": pct(len(fixes), lines),
         "value": None, "severity": sev(len(fixes)), "link": "/store?tab=data-quality#dates"},
        {"key": "unknown_job_card", "label": "Job card not in PPIC register", "count": len(unknown),
         "pct": pct(len(unknown), total), "value": float(value_unknown), "severity": sev(len(unknown)),
         "link": "/store?tab=issues&jc=unknown"},
        {"key": "grn_rate_flag", "label": "GRN rate differs from item rate", "count": rate_flags,
         "pct": pct(rate_flags, len(g_rows)), "value": None, "severity": sev(rate_flags),
         "link": "/store?tab=grns&flag=rate"},
        {"key": "item_no_rate", "label": "Items without rate", "count": no_rate, "pct": None, "value": None,
         "severity": sev(no_rate), "link": "/store?tab=items&rate=missing"},
        {"key": "item_no_head", "label": "Items without stock head", "count": no_head, "pct": None, "value": None,
         "severity": "low", "link": "/store?tab=items&head=missing"},
        {"key": "negative_stock", "label": "Items with negative stock", "count": len(negative), "pct": None,
         "value": float(money(sum((dec(r["value"]) for r in negative), Decimal(0)))) if negative else None,
         "severity": sev(len(negative), high=True), "link": "/store?tab=stock&status=short"},
    ]
    return {
        "period_from": period_from.isoformat(),
        "period_to": period_to.isoformat(),
        "source": source,
        "issue_lines": total,
        "issue_lines_without_jc": len(no_jc),
        "pct_without_jc": pct_no_jc or 0.0,
        "value_without_jc": float(value_no_jc),
        "date_fixes": {"count": len(fixes), "examples": fixes[:10]},
        "checks": checks,
    }
