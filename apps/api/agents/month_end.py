"""Month-end agent: system P&L vs the imported Tally P&L for the last closed month (SPEC 4).

Reads only. Every number comes from ``services.pnl`` (``system_lines``/``tally_lines``, built on
``core.rules.money.job_profit``). Lines whose gap is above the threshold get a plain-word reason
(the Tally note when one was imported, else a standard reason for that head) and a draft journal
entry for the accountant to review: ``amount`` = Tally - system, i.e. what the system is missing.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from agents.base import Agent, AgentContext, Draft, link, register
from agents.collections import inr
from app.services import pnl as pnl_svc

THRESHOLD = Decimal("10000")  # Rs: smaller line gaps are rounding / timing noise
HIGH_SHARE = Decimal("0.10")  # profit gap above 10% of Tally profit -> high severity

# Plain-word reasons when Tally gives no note: (system lower, system higher).
REASONS = {
    "revenue": ("invoices in Tally that are missing or still draft in the system",
                "invoices issued in the system but not yet booked in Tally"),
    "material": ("purchases booked in Tally but not issued to jobs in the store (unissued stock or missing issue slips)",
                 "store issues valued above the Tally purchase cost (check item rates or GRNs booked next month)"),
    "plates": ("plate/die bills in Tally with no plate or die entry in the system",
               "plates/dies entered in the system but their bills not yet booked in Tally"),
    "ink": ("ink bought in Tally but not issued from the store",
            "ink issued from the store but the purchase bill not yet in Tally"),
    "salaries": ("Tally salary includes staff outside the machine crews (office, helpers, bonus)",
                 "crew salary in machine costs above the Tally payroll"),
    "freight": ("freight bills in Tally not linked to delivery challans",
                "challan freight entered in the system but the transporter bill not yet in Tally"),
    "admin": ("admin costs in Tally above the standard admin share",
              "standard admin share above the admin costs booked in Tally"),
    "overheads": ("overheads in Tally (power, rent, repairs) not entered as machine costs",
                  "machine overheads in the system above the Tally overheads"),
}


def last_closed_month(today: date) -> str:
    year, month = (today.year - 1, 12) if today.month == 1 else (today.year, today.month - 1)
    return f"{year:04d}-{month:02d}"


def run(ctx: AgentContext) -> list[Draft]:
    month = last_closed_month(ctx.today)
    label_month = date.fromisoformat(month + "-01").strftime("%B")
    evidence = [link(f"/money?tab=pnl&month={month}", f"P&L {date.fromisoformat(month + '-01').strftime('%b %Y')}")]
    system = pnl_svc.system_lines(ctx.db, month)
    tally, notes, _imported = pnl_svc.tally_lines(ctx.db, month)
    if not tally:
        return [Draft(
            severity="low",
            title=f"{label_month} Tally P&L not imported",
            detail=f"System profit for {month} is {inr(system['profit'])}; import the Tally P&L to compare.",
            evidence=evidence, action_type="none", payload={}, dedupe_key=f"month_end:{month}:no_tally",
        )]

    zero = Decimal("0.00")
    reasons, entries = [], []
    for key, label in pnl_svc.LINES:
        s, t = system[key], tally.get(key, zero)
        diff = t - s  # what the system is missing vs Tally
        if abs(diff) <= THRESHOLD:
            continue
        lower, higher = REASONS.get(key, ("amount booked in Tally but not in the system",
                                          "amount in the system but not booked in Tally"))
        why = notes.get(key) or (lower if diff > 0 else higher)
        direction = "lower" if diff > 0 else "higher"
        reasons.append(f"{label}: system {inr(s)} vs Tally {inr(t)} ({direction} by {inr(abs(diff))}): {why}")
        entries.append({"account": label.split(" (")[0], "amount": float(diff), "note": why})

    s_profit, t_profit = system["profit"], tally.get("profit", zero)
    gap = s_profit - t_profit
    if not entries and abs(gap) <= THRESHOLD:
        return []
    share = abs(gap) / abs(t_profit) if t_profit else Decimal("1")
    title = f"{label_month} profit: system {inr(s_profit)} vs Tally {inr(t_profit)}"
    detail = (f"Gap {inr(abs(gap))} ({'system higher' if gap > 0 else 'system lower'}). "
              + ("Lines above " + inr(THRESHOLD) + ": " + "; ".join(reasons) + "."
                 if reasons else "No single line is above the threshold; small gaps add up."))
    facts = {"month": month, "system_profit": inr(s_profit), "tally_profit": inr(t_profit)}
    worded = ctx.word("finding_title", facts, title)
    if not worded or inr(s_profit) not in worded or inr(t_profit) not in worded:
        worded = title
    return [Draft(
        severity="high" if share > HIGH_SHARE else "medium",
        title=worded,
        detail=detail,
        evidence=evidence,
        action_type="draft_journal",
        payload={"month": month, "entries": entries},
        dedupe_key=f"month_end:{month}",
    )]


AGENT = register(Agent(
    name="month_end",
    label="Month end",
    description="P&L system vs Tally, unbooked costs",
    schedule="monthly, day 5",
    run=run,
))
