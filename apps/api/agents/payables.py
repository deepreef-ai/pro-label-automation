"""Payables agent: this week's supplier payment plan (SPEC 4).

Reads only. Bills, balances and MSME due dates come from ``services.payables.bill_dicts``
(``core.rules.money.supplier_due_date``); the FIFO split of each planned payment comes from
``services.payables.plan_payment`` (``fifo_allocate``). Cash available = the cash plan's opening
bank balance minus its minimum cash (``services.cashplan._settings``).

Plan: bills that are overdue or due within 7 days, MSME bills first, then oldest first; a bill
is planned only if it fits in the cash left, and per vendor only an oldest-first prefix is
planned so the FIFO allocation of the payment matches the plan. One ``schedule_payment``
finding per vendor, plus one ``none`` finding listing bills the cash does not cover.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from agents.base import Agent, AgentContext, Draft, link, register
from agents.collections import day_month, inr, short_inr
from app.services import cashplan as cp_svc
from app.services import payables as pay_svc

WINDOW_DAYS = pay_svc.DUE_SOON_DAYS
PAY_BEFORE_DUE_DAYS = 2  # schedule a payment two days before the due date (bank lead time)
MODE = "neft"


def _pay_on(today: date, due: date) -> date:
    return max(today + timedelta(days=1), due - timedelta(days=PAY_BEFORE_DUE_DAYS))


def run(ctx: AgentContext) -> list[Draft]:
    vendors = pay_svc.vendor_rows(ctx.db)
    bills = [b for b in pay_svc.bill_dicts(ctx.db, as_of=ctx.today, vendors=vendors) if b["balance"] > 0]
    horizon = ctx.today + timedelta(days=WINDOW_DAYS)
    due = [b for b in bills if date.fromisoformat(b["due_date"]) <= horizon]
    if not due:
        return []
    _, opening, min_cash = cp_svc._settings(ctx.db)
    budget = max(opening - min_cash, Decimal("0.00"))
    cash_left = budget

    planned: dict[str, list[dict]] = defaultdict(list)
    blocked: set[str] = set()  # vendors with a skipped older bill: later bills would break FIFO
    deferred: list[dict] = []
    for b in sorted(due, key=lambda b: (not b["msme"], b["date"], b["id"])):
        bal = Decimal(str(b["balance"]))
        older_open = [o for o in bills if o["vendor_id"] == b["vendor_id"] and (o["date"], o["id"]) < (b["date"], b["id"])
                      and o not in planned.get(b["vendor_id"], [])]
        if b["vendor_id"] in blocked or older_open or bal > cash_left:
            deferred.append(b)
            blocked.add(b["vendor_id"])
            continue
        planned[b["vendor_id"]].append(b)
        cash_left -= bal

    drafts: list[Draft] = []
    for vid, vb in planned.items():
        v = vendors[vid]
        amount = sum((Decimal(str(b["balance"])) for b in vb), Decimal("0.00"))
        allocs, _unalloc = pay_svc.plan_payment(ctx.db, vid, amount)
        first_due = min(date.fromisoformat(b["due_date"]) for b in vb)
        pay_on = _pay_on(ctx.today, first_due)
        msme = bool(v["msme"])
        overdue = first_due < ctx.today
        bill_txt = ", ".join(f"{a['bill_no']} ({inr(a['applied'])})" for a in allocs)
        reason = (f"{v['name']} is MSME; the {ctx.settings.get('msme_days', 45)}-day limit makes "
                  if msme else f"{v['name']}: ")
        reason += "; ".join(
            f"bill {b['bill_no']} dated {day_month(date.fromisoformat(b['date']))} "
            f"{'was due' if date.fromisoformat(b['due_date']) < ctx.today else 'due'} on "
            f"{day_month(date.fromisoformat(b['due_date']))}" for b in vb)
        if overdue:
            title = f"{'MSME bill' if msme else 'Bill'} {vb[0]['bill_no']} ({inr(amount)}) overdue since {day_month(first_due)}"
        else:
            days = (first_due - ctx.today).days
            title = (f"{'MSME bill' if msme else 'Bill'}{'s' if len(vb) > 1 else ''} "
                     f"{', '.join(b['bill_no'] for b in vb)} ({inr(amount)}) due in {days} day{'s' if days != 1 else ''}")
        detail = (f"{reason}. Paying {inr(amount)} on {day_month(pay_on)} clears {bill_txt} (FIFO). "
                  f"Bank balance after this week's plan stays at or above {short_inr(min_cash)} "
                  f"(cash available above minimum: {inr(budget)}).")
        drafts.append(Draft(
            severity="high" if msme or overdue else "medium",
            title=title,
            detail=detail,
            evidence=[link(f"/money?tab=creditors&vendor={vid}", f"Creditors: {v['name']}"),
                      link("/money?tab=cashplan", "Cash plan")],
            action_type="schedule_payment",
            payload={"vendor_id": vid, "amount": float(amount), "pay_on": pay_on.isoformat(), "mode": MODE},
            # same keys as core.etl FINDING_KEYS (payables:msme_due:<first bill>) so seeded findings refresh
            dedupe_key=f"payables:{'msme_due' if msme else 'due'}:{vb[0]['id']}",
        ))

    if deferred:
        short = sum((Decimal(str(b["balance"])) for b in deferred), Decimal("0.00"))
        detail = ", ".join(f"{vendors[b['vendor_id']]['name']} {b['bill_no']} ({inr(b['balance'])}, due "
                           f"{day_month(date.fromisoformat(b['due_date']))})" for b in deferred)
        drafts.append(Draft(
            severity="high" if any(b["msme"] for b in deferred) else "medium",
            title=f"{short_inr(short)} of bills due this week do not fit in cash above minimum",
            detail=(f"Not planned: {detail}. Cash left above minimum after the plan: {inr(cash_left)}. "
                    "Collect from at-risk debtors or agree new dates with these suppliers."),
            evidence=[link("/money?tab=creditors", "Creditors"), link("/money?tab=cashplan", "Cash plan")],
            action_type="none",
            payload={},
            dedupe_key="payables:deferred:" + ",".join(sorted(b["id"] for b in deferred)),
        ))
    return drafts


AGENT = register(Agent(
    name="payables",
    label="Payables",
    description="MSME and due supplier bills; payment plan",
    schedule="daily 07:00",
    run=run,
))
