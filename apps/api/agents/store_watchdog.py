"""Store watchdog: GRN rates vs item master, issues without job card, below-min, slow stock, counts.

Reads only. Rate checks use ``core.rules.store.grn_rate_flag`` (through ``app.services.store``),
stock comes from ``store.stock_rows`` (same numbers as the Store screen).
"""
from __future__ import annotations

from datetime import timedelta
from decimal import ROUND_CEILING, Decimal

from sqlalchemy import select

from agents._util_rules import inr, join_names, num, pct, rate, word
from agents.base import Agent, AgentContext, Draft, link, register
from app.deps import T
from app.services import store as store_svc
from core.rules.errors import dec, money

GRN_LOOKBACK_DAYS = 60  # GRNs older than this were already looked at
NO_JC_TOL = 0.05  # share of non-ink issue lines without a job card that is worth raising
REORDER_ROLL_M = Decimal(1000)  # roll items are bought in whole 1,000 m rolls
PURCHASE_LEAD_DAYS = 7


def _grn_findings(ctx: AgentContext, tol: dict) -> list[Draft]:
    since = ctx.today - timedelta(days=GRN_LOOKBACK_DAYS)
    all_grns = store_svc.list_grns(ctx.db, until=ctx.today, tol=tol)
    items = store_svc.items_by_id(ctx.db, {g["item_id"] for g in all_grns})
    out = []
    for g in all_grns:
        if g["date"] is None or g["date"] < since.isoformat():
            continue
        # exact difference for the text (the Grn wire field is rounded to 4 places)
        diff = float((dec(g["rate"]) - dec(g["item_rate"])) / dec(g["item_rate"])) if g["item_rate"] else 0.0
        it = items.get(g["item_id"])
        unit = "sq m" if store_svc.is_sqm_item(it) else (g["uom"] or "unit")
        evidence = [link(f"/store?tab=grns&id={g['id']}", g["id"])]
        if g["vendor_id"]:
            evidence.append(link(f"/money?tab=creditors&vendor={g['vendor_id']}", f"Bill {g['bill_no']}"))
        if g["rate_flag"]:
            extra = money(store_svc.line_value(g["qty"], it, g["rate"]) - store_svc.line_value(g["qty"], it, g["item_rate"]))
            prev = [p for p in all_grns if p["item_id"] == g["item_id"] and (p["date"], p["id"]) < (g["date"], g["id"])][-3:]
            history = ""
            if prev:
                rates = {p["rate"] for p in prev}
                history = (f" Last {len(prev)} GRN{'s were' if len(prev) > 1 else ' was'} at {rate(prev[0]['rate'])}."
                           if len(rates) == 1 else
                           f" Last {len(prev)} GRNs: {', '.join(rate(p['rate']) for p in prev)}.")
            direction = "above" if diff > 0 else "below"
            title = f"{g['id']}: {g['item_name']} rate {pct(abs(diff))} {direction} item master"
            fallback = (f"{g['vendor_name'] or 'The vendor'} billed {rate(g['rate'])}/{unit} against master rate "
                        f"{rate(g['item_rate'])} (tolerance {pct(tol['grn_rate_tol'], 0)}). "
                        f"{'Extra cost' if extra > 0 else 'Difference'} {inr(abs(extra))} on "
                        f"{num(g['qty'])} {g['uom']}.{history}")
            facts = {"grn": g["id"], "vendor": g["vendor_name"], "rate": g["rate"], "item_rate": g["item_rate"],
                     "extra": float(extra), "tolerance": tol["grn_rate_tol"]}
            if extra > 0 and g["vendor_id"]:
                action, payload = "draft_messages", {"messages": [{
                    "channel": "email",
                    "to": g["vendor_name"],
                    "subject": f"Rate difference on bill {g['bill_no']}",
                    "body": (f"Please issue a credit note for {inr(extra)} (rate {rate(g['rate'])} vs agreed "
                             f"{rate(g['item_rate'])} per {unit})."),
                }]}
            else:
                action, payload = "notify", {"to": "store"}
            out.append(Draft(
                severity="high" if abs(diff) >= 2 * tol["grn_rate_tol"] and extra >= 5000 else "medium",
                title=title, detail=word(ctx, "store_watchdog.grn_rate", facts, fallback),
                evidence=evidence, action_type=action, payload=payload,
                dedupe_key=f"store_watchdog:grn_rate:{g['id']}",
            ))
        elif diff > tol["grn_rate_tol"] / 2:
            # under tolerance but more than half way there: tell the store, no vendor message
            out.append(Draft(
                severity="low",
                title=f"{g['id']} {g['item_name']} rate {pct(diff)} above master",
                detail=f"Below {pct(tol['grn_rate_tol'], 0)} tolerance ({rate(g['rate'])} vs {rate(g['item_rate'])}); "
                       f"check the PO rate before the next order.",
                evidence=evidence[:1], action_type="notify", payload={"to": "store"},
                dedupe_key=f"store_watchdog:grn_rate_watch:{g['id']}",
            ))
    return out


def _no_job_card(ctx: AgentContext) -> list[Draft]:
    first = ctx.today.replace(day=1)
    issues = store_svc.list_issues(ctx.db, since=first, until=ctx.today)
    items = store_svc.items_by_id(ctx.db, {i["item_id"] for i in issues})
    # ink and varnish go to the monthly ink pool without a job card (SPEC 2): not a gap
    lines = [i for i in issues if (items.get(i["item_id"]) is None
                                   or (items[i["item_id"]].group or "") not in store_svc.INK_GROUPS)]
    missing = [i for i in lines if not i["job_card"]]
    if not lines or not missing:
        return []
    share = len(missing) / len(lines)
    if share <= NO_JC_TOL:
        return []
    value = money(sum((dec(i["value"]) for i in missing), Decimal(0)))
    month = ctx.today.strftime("%b %Y")
    return [Draft(
        severity="high" if share > 2 * NO_JC_TOL else "medium",
        title=f"{len(missing)} of {len(lines)} paper/film issues in {month} have no job card ({pct(share)})",
        detail=word(ctx, "store_watchdog.no_jc", {"count": len(missing), "lines": len(lines), "value": float(value)},
                    f"{inr(value)} of material went out without a job card, so it cannot be costed to a job "
                    f"(limit {pct(NO_JC_TOL, 0)}; ink and varnish are pooled and not counted). "
                    f"Lines: {join_names([i['id'] for i in missing], 5)}."),
        evidence=[link("/store?tab=issues&jc=missing", "Issues without job card")],
        action_type="notify", payload={"to": "store"},
        dedupe_key=f"store_watchdog:no_jc:{ctx.today.strftime('%Y-%m')}",
    )]


def _below_min(ctx: AgentContext, rows: list[dict]) -> list[Draft]:
    items = store_svc.items_by_id(ctx.db, {r["item_id"] for r in rows if r["status"] in ("low", "short")})
    vendors = {}
    if items:
        v = T("vendors")
        vendors = {r.id: r.name for r in ctx.db.execute(select(v.c.id, v.c.name))}
    out = []
    for r in rows:
        if r["status"] not in ("low", "short"):
            continue
        it = items[r["item_id"]]
        gap = max(dec(r["min_stock"]) - dec(r["stock"]), Decimal(0))
        if r["uom"] == store_svc.ROLL_UOM:
            suggested = max((gap / REORDER_ROLL_M).to_integral_value(rounding=ROUND_CEILING) * REORDER_ROLL_M,
                            REORDER_ROLL_M)
        else:
            suggested = dec(r["min_stock"]) - dec(r["stock"])
        vendor = vendors.get(it.vendor_id, "")
        out.append(Draft(
            severity="high" if r["status"] == "short" else "medium",
            title=f"{r['item_name']} below minimum stock: {num(r['stock'])} of {num(r['min_stock'])} {r['uom']}",
            detail=word(ctx, "store_watchdog.below_min", {"item": r["item_name"], "stock": r["stock"],
                                                          "min": r["min_stock"]},
                        f"Stock is {num(r['stock'], 2)} {r['uom']} against a minimum of {num(r['min_stock'])} "
                        f"{r['uom']} ({num(gap, 2)} {r['uom']} short of the minimum). "
                        f"Suggest {num(suggested)} {r['uom']}" + (f" from {vendor}." if vendor else ".")),
            evidence=[link(f"/store?tab=stock&item={r['item_id']}", f"Stock {r['item_name']}")],
            action_type="draft_purchase_request",
            payload={"item_id": r["item_id"], "qty_m": float(gap), "suggested_qty_m": float(suggested),
                     "vendor_id": it.vendor_id or "",
                     "needed_by": (ctx.today + timedelta(days=PURCHASE_LEAD_DAYS)).isoformat()},
            dedupe_key=f"store_watchdog:below_min:{r['item_id']}",
        ))
    return out


def _non_moving(ctx: AgentContext, rows: list[dict]) -> list[Draft]:
    slow = sorted((r for r in rows if r["status"] == "non_moving"), key=lambda r: -r["value"])
    if not slow:
        return []
    value = money(sum((dec(r["value"]) for r in slow), Decimal(0)))
    top = [f"{r['item_name']} ({inr(r['value'])}, last moved {r['last_movement']})" for r in slow[:3]]
    return [Draft(
        severity="medium" if value >= 100000 else "low",
        title=f"{len(slow)} items with no movement for {store_svc.NON_MOVING_DAYS}+ days: {inr(value)} of stock",
        detail=word(ctx, "store_watchdog.non_moving", {"items": len(slow), "value": float(value)},
                    f"Largest: {join_names(top, 3)}. Plan them into open jobs, slit jumbos to running widths, "
                    f"or return to the vendor."),
        evidence=[link("/store?tab=stock&status=non_moving", "Non-moving stock")],
        action_type="notify", payload={"to": "store"},
        dedupe_key=f"store_watchdog:non_moving:{ctx.today.strftime('%Y-%m')}",
    )]


def _count_differences(ctx: AgentContext) -> list[Draft]:
    """Physical count at the opening stock take vs the book quantity."""
    op = T("opening_stock")
    rows = ctx.db.execute(select(op.c.item_id, op.c.qty, op.c.physical_count, op.c.as_of)
                          .where(op.c.physical_count.is_not(None))).all()
    diffs = [r for r in rows if dec(r.physical_count) != dec(r.qty or 0)]
    if not diffs:
        return []
    items = store_svc.items_by_id(ctx.db, {r.item_id for r in diffs})
    value = money(sum((abs(store_svc.line_value(dec(r.physical_count) - dec(r.qty or 0), items.get(r.item_id)))
                       for r in diffs), Decimal(0)))
    names = [f"{(items[r.item_id].name if r.item_id in items else r.item_id)} "
             f"(book {num(r.qty, 2)}, counted {num(r.physical_count, 2)})" for r in diffs]
    return [Draft(
        severity="medium" if value >= 10000 else "low",
        title=f"{len(diffs)} items counted differently from book stock ({inr(value)})",
        detail=f"Stock take differences: {join_names(names, 4)}. Check and post a stock adjustment.",
        evidence=[link("/store?tab=stock", "Stock")],
        action_type="notify", payload={"to": "store"},
        dedupe_key="store_watchdog:count_diff:" + str(max(r.as_of for r in diffs if r.as_of) if any(
            r.as_of for r in diffs) else "na"),
    )]


def run(ctx: AgentContext) -> list[Draft]:
    tol = store_svc.store_tolerances(ctx.db)
    rows = store_svc.stock_rows(ctx.db, tol)
    return [*_grn_findings(ctx, tol), *_no_job_card(ctx), *_below_min(ctx, rows), *_non_moving(ctx, rows),
            *_count_differences(ctx)]


AGENT = register(Agent(
    name="store_watchdog",
    label="Store watchdog",
    description="GRN rates, issues without job card, below-min stock",
    schedule="daily 07:00",
    run=run,
))
