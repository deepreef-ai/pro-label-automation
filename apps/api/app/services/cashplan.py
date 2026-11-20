"""6-month cash plan: money in vs money out, month by month (no LLM; rules compute every number).

Months run from ``today()``'s month for 6 months. Anything already overdue falls in the first month.

- ``inflow_collections`` - outstanding of issued invoices by due date (``services.clients.invoice_dicts``),
  plus projected sales: the run-rate (average invoice total of the last 3 closed months) billed on
  each month (current month: only what is not invoiced yet) and collected ``round(credit days / 30)``
  months later, using the amount-weighted average credit days (due date - invoice date) of the
  run-rate invoices (spreading month-end due dates evenly instead of bunching them).
- ``outflow_suppliers`` - open supplier bill balances by due date (MSME rule, ``services.payables``),
  plus projected purchases at the bills run-rate, paid after the average effective credit days
  (due date - bill date, so the MSME cap is included) in whole months, as for sales.
- ``outflow_salaries`` / ``outflow_overheads`` - average monthly crew salary / other cost in
  ``machine_costs`` over the last 3 closed months.
- ``outflow_gst`` - GST of the previous month paid this month: output GST on invoices minus
  input GST inside supplier bills (bills include GST), never below zero.
- ``outflow_other`` - admin & finance share (``admin_share``) of the month's projected taxable sales.
- ``closing`` = opening + inflow - outflows; ``low_cash`` when closing < ``min_cash``.

The bank balance at the start of the plan and ``min_cash`` are inputs, not data the system
records: they come from ``settings.extra`` (``opening_cash``, ``min_cash``) when set, else the
demo defaults below.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.deps import T, today
from app.services.clients import invoice_dicts
from app.services.payables import bill_dicts
from core.rules import money as M

MONTHS = 6
BASE_MONTHS = 3  # run-rate window: the last closed months before today's month
DAYS_PER_MONTH = 30  # credit days -> whole months of lag for projected invoices and bills
DEFAULT_OPENING_CASH = Decimal("1840000.00")
DEFAULT_MIN_CASH = Decimal("1500000.00")
ZERO = Decimal("0.00")


def _key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def _add_months(d: date, n: int) -> date:
    idx = d.year * 12 + d.month - 1 + n
    return date(idx // 12, idx % 12 + 1, 1)


def _settings(db: Session) -> tuple[dict, Decimal, Decimal]:
    from app.routers.shell import load_settings  # local import: routers import services

    s = load_settings(db)
    st = T("settings")
    extra = {}
    if "extra" in st.c:
        extra = db.execute(select(st.c.extra).limit(1)).scalar() or {}
    gst = Decimal(str(s.get("gst_rate") if s.get("gst_rate") is not None else M.DEFAULTS.gst_rate))
    admin = Decimal(str(s.get("admin_pct") if s.get("admin_pct") is not None else M.DEFAULTS.admin_pct))
    opening = M.money(extra.get("opening_cash", DEFAULT_OPENING_CASH)) if isinstance(extra, dict) else DEFAULT_OPENING_CASH
    min_cash = M.money(extra.get("min_cash", DEFAULT_MIN_CASH)) if isinstance(extra, dict) else DEFAULT_MIN_CASH
    return {"gst_rate": gst, "admin_pct": admin}, opening, min_cash


def _lag(days: int) -> int:
    """Whole months between billing and payment for a projected invoice or bill."""
    return max(int((Decimal(days) / DAYS_PER_MONTH).quantize(Decimal("1"))), 0)


def _avg_days(pairs: list[tuple[int, Decimal]], default: int) -> int:
    """Amount-weighted average of day offsets (rounded), ``default`` when there is nothing."""
    total = sum((a for _, a in pairs), ZERO)
    if total <= 0:
        return default
    return int((sum((Decimal(d) * a for d, a in pairs), ZERO) / total).quantize(Decimal("1")))


def cashplan(db: Session) -> dict:
    as_of = today()
    start = as_of.replace(day=1)
    months = [_key(_add_months(start, i)) for i in range(MONTHS)]
    first_key = months[0]
    base = {_key(_add_months(start, -i)) for i in range(1, BASE_MONTHS + 1)}
    cfg, opening, min_cash = _settings(db)
    gst_rate = cfg["gst_rate"]

    def bucket(due: date) -> str | None:
        k = _key(due)
        if k < first_key:
            return first_key  # overdue: plan to settle it now
        return k if k in months else None

    inflow: dict[str, Decimal] = defaultdict(Decimal)
    suppliers: dict[str, Decimal] = defaultdict(Decimal)
    out_gst: dict[str, Decimal] = defaultdict(Decimal)  # by billing month
    in_gst: dict[str, Decimal] = defaultdict(Decimal)  # by purchase month

    # ---- receivables: known invoices, run-rate of sales
    sales_total: dict[str, Decimal] = defaultdict(Decimal)
    sales_taxable: dict[str, Decimal] = defaultdict(Decimal)
    credit_pairs: list[tuple[int, Decimal]] = []
    for inv in invoice_dicts(db, as_of=as_of):
        if inv["status"] == "draft":
            continue
        inv_date, due = date.fromisoformat(inv["date"]), date.fromisoformat(inv["due_date"])
        mk, total = _key(inv_date), Decimal(str(inv["total"]))
        sales_total[mk] += total
        sales_taxable[mk] += Decimal(str(inv["taxable"]))
        out_gst[mk] += Decimal(str(inv["gst"]))
        if mk in base:
            credit_pairs.append(((due - inv_date).days, total))
        if inv["outstanding"] > 0:
            k = bucket(due)
            if k:
                inflow[k] += Decimal(str(inv["outstanding"]))
    rate_total = M.money(sum((sales_total[k] for k in base), ZERO) / BASE_MONTHS)
    rate_taxable = M.money(sum((sales_taxable[k] for k in base), ZERO) / BASE_MONTHS)
    rate_gst = M.money(sum((out_gst[k] for k in base), ZERO) / BASE_MONTHS)
    client_days = _avg_days(credit_pairs, M.DEFAULTS.credit_days)

    projected_taxable: dict[str, Decimal] = {}
    for i, mk in enumerate(months):
        if i == 0:  # this month: only what is not invoiced yet
            share = (max(rate_total - sales_total[mk], ZERO) / rate_total) if rate_total else ZERO
        else:
            share = Decimal(1)
        k = bucket(_add_months(start, i + _lag(client_days)))
        if k:
            inflow[k] += M.money(rate_total * share)
        projected_taxable[mk] = M.money(rate_taxable * share)
        out_gst[mk] += M.money(rate_gst * share)

    # ---- payables: open bills, run-rate of purchases
    bills_total: dict[str, Decimal] = defaultdict(Decimal)
    vendor_pairs: list[tuple[int, Decimal]] = []
    for b in bill_dicts(db, as_of=as_of):
        bill_date, due = date.fromisoformat(b["date"]), date.fromisoformat(b["due_date"])
        mk, amount = _key(bill_date), Decimal(str(b["amount"]))
        bills_total[mk] += amount
        if mk in base:
            vendor_pairs.append(((due - bill_date).days, amount))
        if b["balance"] > 0:
            k = bucket(due)
            if k:
                suppliers[k] += Decimal(str(b["balance"]))
    rate_bills = M.money(sum((bills_total[k] for k in base), ZERO) / BASE_MONTHS)
    vendor_days = _avg_days(vendor_pairs, M.DEFAULTS.credit_days)
    for i, mk in enumerate(months):
        share = (max(rate_bills - bills_total[mk], ZERO) / rate_bills if rate_bills else ZERO) if i == 0 \
            else Decimal(1)
        purchase = M.money(rate_bills * share)
        k = bucket(_add_months(start, i + _lag(vendor_days)))
        if k:
            suppliers[k] += purchase
        bills_total[mk] += purchase
    for mk, amount in bills_total.items():
        in_gst[mk] += M.money(amount * gst_rate / (1 + gst_rate))

    # ---- fixed costs: machine_costs run-rate
    mc = T("machine_costs")
    crew, other = db.execute(select(func.sum(mc.c.crew_salary), func.sum(mc.c.other_cost))
                             .where(mc.c.month.in_(base))).one()
    salaries = M.money(Decimal(str(crew or 0)) / BASE_MONTHS)
    overheads = M.money(Decimal(str(other or 0)) / BASE_MONTHS)

    rows = []
    cash = opening
    for i, mk in enumerate(months):
        prev = _key(_add_months(start, i - 1))
        gst = max(M.money(out_gst[prev]) - M.money(in_gst[prev]), ZERO)
        other_out = M.admin_share(projected_taxable[mk] + (sales_taxable[mk] if i == 0 else ZERO), cfg["admin_pct"])
        cin = M.money(inflow[mk])
        sup = M.money(suppliers[mk])
        closing = cash + cin - sup - salaries - overheads - gst - other_out
        rows.append({
            "month": mk, "opening": float(cash), "inflow_collections": float(cin), "outflow_suppliers": float(sup),
            "outflow_salaries": float(salaries), "outflow_overheads": float(overheads), "outflow_gst": float(gst),
            "outflow_other": float(other_out), "closing": float(closing), "low_cash": closing < min_cash,
        })
        cash = closing
    return {"as_of": as_of.isoformat(), "min_cash": float(min_cash), "months": rows}
