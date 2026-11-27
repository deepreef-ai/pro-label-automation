"""LOCKED money rules: lock boundary, MSME dues, FIFO, ageing, GST (SPEC 2)."""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from core.rules import RuleError
from core.rules.money import (
    Bill,
    ageing_bucket,
    client_locked,
    due_date,
    fifo_allocate,
    invoice_amounts,
    is_locked,
    job_profit,
    supplier_due_date,
)

DUE = date(2026, 5, 1)


# ---- Lock boundary ---------------------------------------------------------------------

def test_lock_boundary():
    assert is_locked(DUE, DUE) is False
    assert is_locked(DUE, DUE + timedelta(days=15)) is False
    assert is_locked(DUE, DUE + timedelta(days=16)) is True


def test_paid_invoice_never_locks():
    assert is_locked(DUE, DUE + timedelta(days=400), paid=True) is False


def test_client_locked_any_invoice():
    as_of = DUE + timedelta(days=16)
    ok = {"due_date": DUE + timedelta(days=10), "balance": 500}
    late_paid = {"due_date": DUE, "paid": True}
    late_unpaid = {"due_date": DUE, "balance": 1}
    assert client_locked([ok, late_paid], as_of) is False
    assert client_locked([ok, late_paid, late_unpaid], as_of) is True
    assert client_locked([{"due_date": DUE, "balance": 0}], as_of) is False


def test_due_date_default_and_custom():
    assert due_date(date(2026, 4, 6)) == date(2026, 5, 6)
    assert due_date(date(2026, 4, 6), 45) == date(2026, 5, 21)
    with pytest.raises(RuleError):
        due_date(date(2026, 4, 6), -1)


# ---- Supplier due ----------------------------------------------------------------------

@pytest.mark.parametrize("credit,msme,days", [(30, True, 30), (60, True, 45), (45, True, 45),
                                              (60, False, 60), (30, False, 30)])
def test_supplier_due_date(credit, msme, days):
    bill = date(2026, 4, 1)
    assert supplier_due_date(bill, credit, msme) == bill + timedelta(days=days)


def test_supplier_due_negative_credit():
    with pytest.raises(RuleError):
        supplier_due_date(date(2026, 4, 1), -5, False)


# ---- FIFO --------------------------------------------------------------------------------

amounts = st.decimals(min_value=0, max_value=100_000, places=2, allow_nan=False, allow_infinity=False)
bill_lists = st.lists(st.tuples(st.integers(min_value=0, max_value=365), amounts), max_size=12)


@given(bill_lists, st.lists(amounts, max_size=5))
def test_fifo_properties(raw_bills, payments):
    bills = [Bill(f"B{i}", date(2026, 1, 1) + timedelta(days=d), a) for i, (d, a) in enumerate(raw_bills)]
    alloc = fifo_allocate(payments, bills)
    paid = sum(payments, Decimal(0))
    due = sum((b.amount for b in bills), Decimal(0))

    assert set(alloc) == {b.id for b in bills}
    for b in bills:
        assert Decimal(0) <= alloc[b.id] <= b.amount
    assert sum(alloc.values(), Decimal(0)) == min(paid, due)

    ordered = sorted(bills, key=lambda b: b.bill_date)
    for i, older in enumerate(ordered):
        if alloc[older.id] < older.amount:  # not fully paid -> no newer bill gets anything
            assert all(alloc[newer.id] == 0 for newer in ordered[i + 1:])


def test_fifo_example_and_guards():
    bills = [Bill("new", date(2026, 3, 1), Decimal("500")), Bill("old", date(2026, 1, 1), Decimal("300"))]
    assert fifo_allocate(400, bills) == {"old": Decimal("300.00"), "new": Decimal("100.00")}
    assert fifo_allocate([1000], bills) == {"old": Decimal("300.00"), "new": Decimal("500.00")}
    with pytest.raises(RuleError):
        fifo_allocate(-1, bills)
    with pytest.raises(RuleError):
        fifo_allocate(1, [Bill("a", DUE, Decimal(1)), Bill("a", DUE, Decimal(2))])
    with pytest.raises(RuleError):
        fifo_allocate(1, [Bill("a", DUE, Decimal(-1))])


# ---- Ageing ------------------------------------------------------------------------------

@pytest.mark.parametrize("days,bucket", [(-5, "not_due"), (0, "not_due"), (1, "1_30"), (30, "1_30"),
                                         (31, "31_60"), (60, "31_60"), (61, "61_90"), (90, "61_90"),
                                         (91, "90_plus")])
def test_ageing_bucket_edges(days, bucket):
    assert ageing_bucket(DUE, DUE + timedelta(days=days)) == bucket


# ---- GST / profit ------------------------------------------------------------------------

def test_gst_18_percent():
    inv = invoice_amounts(1, 30_000)
    assert inv.gst == Decimal("5400.00")
    assert inv.total == Decimal("35400.00")
    assert invoice_amounts(3, "33.333", 0.05).taxable == Decimal("100.00")
    with pytest.raises(RuleError):
        invoice_amounts(-1, 10)


def test_job_profit_zero_revenue():
    p = job_profit(0, material=100)
    assert p.profit == Decimal("-100.00")
    assert p.margin == Decimal("0")
