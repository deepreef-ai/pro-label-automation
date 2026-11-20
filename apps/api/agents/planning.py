"""Planning: paper needed for open jobs vs stock, late / at-risk jobs, press queue load.

Reads only. Paper need comes from ``jobs.material_summary`` (planned metres incl. the planning
extra, minus metres already issued, vs live stock); late jobs use the same ``late`` flag as the
Jobs screen.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from decimal import ROUND_CEILING, Decimal

from sqlalchemy import select

from agents._util_rules import as_date, day, join_names, num, word
from agents.base import Agent, AgentContext, Draft, link, register
from app.deps import T
from app.services import jobs as job_svc
from app.services.production import SHIFT_HOURS
from core.rules.errors import dec

ROLL_M = Decimal(1000)  # paper and film are bought in whole 1,000 m rolls
LEAD_DAYS = 7  # vendor lead time used to warn when an order is already late
BUFFER_DAYS = 3  # paper should be in store this many days before the job is due
AT_RISK_DAYS = 3  # a job due within this many days and not yet printing is at risk
QUEUE_WINDOW_DAYS = 7  # press load: jobs due within a week vs one shift a day
NOT_STARTED = ("planned", "design")


def _shortages(ctx: AgentContext, jobs: list[dict], tol: dict) -> list[Draft]:
    summary = job_svc.material_summary(ctx.db, [j for j in jobs if j["status"] in job_svc.OPEN_FOR_MATERIAL], tol)
    by_card = {j["job_card"]: j for j in jobs}
    it_t, v_t = T("items"), T("vendors")
    vendor_of = {r.id: r.vendor_id for r in ctx.db.execute(select(it_t.c.id, it_t.c.vendor_id))}
    vendor_name = {r.id: r.name for r in ctx.db.execute(select(v_t.c.id, v_t.c.name))}
    out = []
    for it in summary["items"]:
        if it["status"] != "short":
            continue
        short = dec(it["shortage_m"])
        suggested = (short / ROLL_M).to_integral_value(rounding=ROUND_CEILING) * ROLL_M
        cards = [r["job_card"] for r in it["jobs"]]
        dues = sorted((as_date(by_card[c]["due_date"]), c) for c in cards if by_card.get(c, {}).get("due_date"))
        first_due, first_card = dues[0] if dues else (None, None)
        needed_by = max(first_due - timedelta(days=BUFFER_DAYS), ctx.today) if first_due else \
            ctx.today + timedelta(days=LEAD_DAYS)
        vendor_id = vendor_of.get(it["item_id"]) or ""
        late_order = ctx.today + timedelta(days=LEAD_DAYS) > needed_by
        need_list = ", ".join(f"{r['job_card']}: {num(r['need_m'], 2)} m" for r in it["jobs"])
        fallback = (f"Open jobs need {num(it['need_m'], 2)} m ({need_list} incl. "
                    f"{round(summary['planning_extra'] * 100)}% planning extra). Stock is {num(it['stock_m'], 2)} m."
                    + (f" {first_card} is due {day(first_due)}." if first_due else "")
                    + f" Suggest {num(suggested)} m"
                    + (f" from {vendor_name[vendor_id]}" if vendor_id in vendor_name else "")
                    + f" ({LEAD_DAYS}-day lead time)."
                    + (" Order today: the lead time already runs past the date it is needed." if late_order else ""))
        out.append(Draft(
            severity="high" if first_due is None or (first_due - ctx.today).days <= 14 else "medium",
            title=f"{it['material']} short by {num(short)} m for {join_names(cards)}",
            detail=word(ctx, "planning.shortage", {"material": it["material"], "short_m": float(short),
                                                   "jobs": cards}, fallback),
            evidence=[link("/jobs?tab=material", "Material summary"),
                      link(f"/store?tab=stock&item={it['item_id']}", f"Stock {it['material']}")],
            action_type="draft_purchase_request",
            payload={"item_id": it["item_id"], "qty_m": float(short), "suggested_qty_m": float(suggested),
                     "vendor_id": vendor_id, "needed_by": needed_by.isoformat()},
            dedupe_key=f"planning:short:{it['item_id']}",
        ))
    return out


def _late(ctx: AgentContext, jobs: list[dict]) -> list[Draft]:
    out = []
    for j in jobs:
        if "late" not in j["flags"]:
            continue
        due = as_date(j["due_date"])
        days_late = (ctx.today - due).days
        left = j["order_qty"] - j["dispatched_qty"]
        blockers = [f for f in ("client_locked", "qc_hold", "material_short") if f in j["flags"]]
        if j["status"] == "hold":
            blockers.insert(0, "job on hold")
        why = f" Blocked by: {', '.join(b.replace('_', ' ') for b in blockers)}." if blockers else ""
        out.append(Draft(
            severity="high" if days_late >= 3 or j["priority"] == "high" else "medium",
            title=f"{j['job_card']} ({j['client_name']}) is {days_late} day{'s' if days_late != 1 else ''} late",
            detail=word(ctx, "planning.late", {"job": j["job_card"], "days_late": days_late, "status": j["status"]},
                        f"Due {day(due)}, status {j['status']}: {num(j['dispatched_qty'])} of "
                        f"{num(j['order_qty'])} labels dispatched, {num(left)} to go.{why} "
                        f"Agree a new date with the client."),
            evidence=[link(f"/jobs/{j['job_card']}", j["job_card"])],
            action_type="create_task",
            payload={"assign_to": "ppic", "title": f"Agree new delivery date for {j['job_card']} with "
                                                   f"{j['client_name'] or 'the client'}",
                     "due": ctx.today.isoformat()},
            dedupe_key=f"planning:late:{j['job_card']}",
        ))
    return out


def _at_risk(ctx: AgentContext, jobs: list[dict]) -> list[Draft]:
    out = []
    for j in jobs:
        due = as_date(j["due_date"])
        if j["status"] not in NOT_STARTED or due is None or due < ctx.today:
            continue
        left = (due - ctx.today).days
        if left > AT_RISK_DAYS:
            continue
        out.append(Draft(
            severity="high" if left <= 1 else "medium",
            title=f"{j['job_card']} due {day(due)} and still in {j['status']}",
            detail=word(ctx, "planning.at_risk", {"job": j["job_card"], "days_left": left},
                        f"{num(j['order_qty'])} labels for {j['client_name']} are due in {left} day"
                        f"{'s' if left != 1 else ''} but printing has not started"
                        + (" and the paper is short" if "material_short" in j["flags"] else "") + "."),
            evidence=[link(f"/jobs/{j['job_card']}", j["job_card"])],
            action_type="create_task",
            payload={"assign_to": "ppic", "title": f"Move {j['job_card']} up the press queue or reset the date",
                     "due": ctx.today.isoformat()},
            dedupe_key=f"planning:at_risk:{j['job_card']}",
        ))
    return out


def _press_load(ctx: AgentContext, jobs: list[dict]) -> list[Draft]:
    """Hours of printing still to do for jobs due within a week vs one shift a day per press."""
    mc, ps = T("machines"), T("press_setup")
    machines = {r.id: r for r in ctx.db.execute(select(mc.c.id, mc.c.name, mc.c.type, mc.c.max_speed_mpm))}
    speed = {r.job_card: r.speed_target_mpm for r in ctx.db.execute(select(ps.c.job_card, ps.c.speed_target_mpm))}
    horizon = ctx.today + timedelta(days=QUEUE_WINDOW_DAYS)
    load: dict[str, Decimal] = defaultdict(Decimal)
    cards: dict[str, list[str]] = defaultdict(list)
    for j in jobs:
        due = as_date(j["due_date"])
        m = machines.get(j["machine_id"])
        if j["status"] not in job_svc.OPEN_FOR_MATERIAL or due is None or due > horizon or m is None:
            continue
        mpm = dec(speed.get(j["job_card"]) or m.max_speed_mpm or 0)
        if mpm <= 0 or j["order_qty"] <= 0:
            continue
        left_share = max(Decimal(1) - dec(j["printed_qty"]) / dec(j["order_qty"]), Decimal(0))
        hours = dec(j["planned_m"]) * left_share / mpm / 60
        if hours > 0:
            load[j["machine_id"]] += hours
            cards[j["machine_id"]].append(j["job_card"])
    capacity = dec(SHIFT_HOURS * QUEUE_WINDOW_DAYS)
    out = []
    for mid, hours in sorted(load.items()):
        if hours <= capacity:
            continue
        name = machines[mid].name or mid
        out.append(Draft(
            severity="high" if hours > capacity * Decimal("1.5") else "medium",
            title=f"{name} needs {num(hours, 1)} h for jobs due this week (one shift a day = {num(capacity)} h)",
            detail=word(ctx, "planning.press_load", {"machine": name, "hours": float(hours)},
                        f"Jobs due by {day(horizon)}: {join_names(cards[mid], 5)}. Add a night shift or move a "
                        f"job to another press."),
            evidence=[link(f"/production?machine={mid}", name)],
            action_type="notify", payload={"to": "production"},
            dedupe_key=f"planning:press_load:{mid}",
        ))
    return out


def run(ctx: AgentContext) -> list[Draft]:
    tol = job_svc.tolerances(ctx.db)
    jobs = job_svc.list_jobs(ctx.db, tol=tol)
    return [*_shortages(ctx, jobs, tol), *_late(ctx, jobs), *_at_risk(ctx, jobs), *_press_load(ctx, jobs)]


AGENT = register(Agent(
    name="planning",
    label="Planning",
    description="Paper needed for open jobs vs stock, late jobs",
    schedule="daily 07:00",
    run=run,
))
