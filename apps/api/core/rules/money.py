"""Money rules: invoices, credit lock, ageing, supplier dues, FIFO, job profit (SPEC 2).

All amounts are Decimal rounded to 2 decimals (half-up).
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from .errors import Number, RuleError, dec, field, money
from .settings import DEFAULTS


@dataclass(frozen=True)
class InvoiceAmounts:
    """Taxable value, GST and invoice total."""

    taxable: Decimal
    gst: Decimal
    total: Decimal


def invoice_amounts(qty: Number, rate: Number, gst_rate: Number = DEFAULTS.gst_rate) -> InvoiceAmounts:
    """Invoice: taxable = qty * rate; GST = taxable * gst_rate (default 0.18) (SPEC 2, bullet 11)."""
    if dec(qty) < 0 or dec(rate) < 0 or dec(gst_rate) < 0:
        raise RuleError("qty, rate and GST rate must not be negative")
    taxable = money(dec(qty) * dec(rate))
    gst = money(taxable * dec(gst_rate))
    return InvoiceAmounts(taxable=taxable, gst=gst, total=taxable + gst)


def due_date(invoice_date: date, credit_days: int | None = None) -> date:
    """Due date = invoice date + client credit days (default 30) (SPEC 2, bullet 11)."""
    days = DEFAULTS.credit_days if credit_days is None else credit_days
    if days < 0:
        raise RuleError("credit days must not be negative")
    return invoice_date + timedelta(days=days)


def is_locked(due: date, as_of: date, paid: bool = False,
              grace_days: int = DEFAULTS.grace_days) -> bool:
    """An unpaid invoice locks its client on any day AFTER due + grace_days (SPEC 2, bullet 12).

    Day due+15 is not locked, due+16 is (default grace 15). A paid invoice never locks.
    """
    if paid:
        return False
    return as_of > due + timedelta(days=grace_days)


def client_locked(invoices: Iterable[Any], as_of: date, grace_days: int = DEFAULTS.grace_days) -> bool:
    """A client is LOCKED when any of its invoices is locked (SPEC 2, bullet 12).

    Invoices are dicts/objects with ``due_date`` and either ``paid`` or ``balance``
    (balance > 0 = unpaid). Owner release is handled by the caller, not here.
    """
    for inv in invoices:
        paid = field(inv, "paid")
        if paid is None:
            paid = dec(field(inv, "balance", 0) or 0) <= 0
        if is_locked(field(inv, "due_date"), as_of, bool(paid), grace_days):
            return True
    return False


def ageing_bucket(due: date, as_of: date) -> str:
    """Ageing bucket by days past due: not_due (<=0), 1_30, 31_60, 61_90, 90_plus (SPEC 2, bullet 13)."""
    days = (as_of - due).days
    if days <= 0:
        return "not_due"
    if days <= 30:
        return "1_30"
    if days <= 60:
        return "31_60"
    if days <= 90:
        return "61_90"
    return "90_plus"


def supplier_due_date(bill_date: date, credit_days: int, is_msme: bool,
                      msme_days: int = DEFAULTS.msme_days) -> date:
    """Supplier bill due = bill date + min(credit, 45) for MSME vendors, else + credit days (SPEC 2, bullet 14)."""
    if credit_days < 0:
        raise RuleError("credit days must not be negative")
    days = min(credit_days, msme_days) if is_msme else credit_days
    return bill_date + timedelta(days=days)


@dataclass(frozen=True)
class Bill:
    """An open bill (supplier bill or customer invoice) for FIFO settlement."""

    id: str
    bill_date: date
    amount: Decimal


def fifo_allocate(payments: Number | Iterable[Number], bills: Sequence[Bill]) -> dict[str, Decimal]:
    """Payments clear the oldest bill first (FIFO) (SPEC 2, bullet 14).

    ``payments`` is one amount or a list of amounts (pooled). Bills are ordered by
    ``bill_date`` then input order. Returns ``{bill_id: allocated}`` for every bill
    (0.00 when nothing reached it). Total allocated = min(total paid, total due);
    any excess is an advance left to the caller.
    """
    if isinstance(payments, (int, float, Decimal, str)):
        payments = [payments]
    remaining = sum((money(p) for p in payments), Decimal("0.00"))
    if remaining < 0:
        raise RuleError("total payment must not be negative")
    ids = [b.id for b in bills]
    if len(set(ids)) != len(ids):
        raise RuleError("bill ids must be unique")
    result: dict[str, Decimal] = {}
    for bill in sorted(bills, key=lambda b: b.bill_date):  # sorted() is stable
        amount = money(bill.amount)
        if amount < 0:
            raise RuleError("bill amount must not be negative")
        take = min(amount, remaining)
        result[bill.id] = take
        remaining -= take
    return result


def revenue_for_job(invoiced_taxable: Number, po_value: Number) -> Decimal:
    """Job revenue = invoiced taxable value, else PO value when nothing is invoiced (SPEC 2, bullet 15)."""
    inv = money(invoiced_taxable or 0)
    return inv if inv > 0 else money(po_value or 0)


def po_value(order_qty: Number, rate: Number) -> Decimal:
    """PO value = order qty * PO rate (used as revenue before invoicing, SPEC 2 bullet 15)."""
    return money(dec(order_qty) * dec(rate))


def admin_share(revenue: Number, admin_pct: Number = DEFAULTS.admin_pct) -> Decimal:
    """Admin & finance share = revenue * admin_pct (default 0.05) (SPEC 2, bullets 15-16)."""
    return money(dec(revenue) * dec(admin_pct))


@dataclass(frozen=True)
class JobProfit:
    """Job P&L breakdown."""

    revenue: Decimal
    material: Decimal
    plates: Decimal
    ink: Decimal
    salaries: Decimal
    freight: Decimal
    admin_share: Decimal
    direct_overhead: Decimal
    total_cost: Decimal
    profit: Decimal
    margin: Decimal  # profit / revenue, 4 places; 0 when revenue is 0


def job_profit(revenue: Number, material: Number = 0, plates: Number = 0, ink: Number = 0,
               salaries: Number = 0, freight: Number = 0, admin_share: Number = 0,
               direct_overhead: Number = 0) -> JobProfit:
    """Job profit = revenue - material - plates - ink - salaries - freight - admin_share - direct_overhead (SPEC 2, bullet 15)."""
    parts = [money(x) for x in (material, plates, ink, salaries, freight, admin_share, direct_overhead)]
    rev = money(revenue)
    total = sum(parts, Decimal("0.00"))
    profit = rev - total
    margin = (profit / rev).quantize(Decimal("0.0001")) if rev else Decimal("0")
    return JobProfit(rev, *parts, total_cost=total, profit=profit, margin=margin)
