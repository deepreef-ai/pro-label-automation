"""LOCKED guards: dispatch, QC, job card, ERP dates, tolerance edges, press-only totals (SPEC 2)."""
from datetime import date, datetime
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from core.rules import RuleError
from core.rules.dates import parse_erp_date
from core.rules.errors import ratio
from core.rules.production import (
    crew_cost,
    machine_hour_rate,
    oee,
    printed_total_press_only,
    required_metres,
    ups,
    wastage,
    wastage_flag,
)
from core.rules.quality import approved_total, check_dispatch, dispatch_allowed, qc_validate
from core.rules.store import ink_pool_allocation, metres_to_sqm, require_job_card, slit_trim_pct

# ---- Dispatch ------------------------------------------------------------------------------

def test_dispatch_cumulative_equal_ok_plus_one_raises():
    assert check_dispatch(1000, 600, 400) == 1000
    assert dispatch_allowed(1000, 600, 400) is True
    assert dispatch_allowed(1000, 600, 401) is False
    with pytest.raises(RuleError):
        check_dispatch(1000, 600, 401)
    with pytest.raises(RuleError):
        check_dispatch(1000, 0, 0)
    assert dispatch_allowed(1000, 0, 0) is False


# ---- QC ------------------------------------------------------------------------------------

def test_qc_validate():
    qc_validate(printed=1000, checked=1000, approved=950, rejected=50)
    with pytest.raises(RuleError, match="must equal checked"):
        qc_validate(printed=1000, checked=1000, approved=950, rejected=49)
    with pytest.raises(RuleError, match="cannot exceed printed"):
        qc_validate(printed=999, checked=1000, approved=950, rejected=50)
    with pytest.raises(RuleError):
        qc_validate(printed=10, checked=0, approved=-1, rejected=1)


def test_hold_rework_rejected_not_approved():
    rows = [
        {"approved_qty": 500, "decision": "Approved"},
        {"approved_qty": 200, "decision": "Hold"},
        {"approved_qty": 300, "decision": "rework"},
        {"approved_qty": 400, "decision": " REJECTED "},
        {"approved_qty": 100, "decision": None},
    ]
    assert approved_total(rows) == 600


# ---- Job card ------------------------------------------------------------------------------

@pytest.mark.parametrize("jc", [None, "", "   ", "1301", "JC1301", "JC-12"])
def test_issue_without_valid_job_card_raises(jc):
    with pytest.raises(RuleError):
        require_job_card(jc)


def test_require_job_card_ok_and_unknown():
    assert require_job_card(" jc-1301 ") == "JC-1301"
    assert require_job_card("JC-1301", {"JC-1301"}) == "JC-1301"
    with pytest.raises(RuleError, match="unknown"):
        require_job_card("JC-9999", {"JC-1301"})


# ---- ERP dates -----------------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("06-04-26", date(2026, 4, 6)),
    ("11-05-2026", date(2026, 5, 11)),
    ("6/4/26", date(2026, 4, 6)),
    ("31.12.2026", date(2026, 12, 31)),
    ("2026-04-06", date(2026, 4, 6)),
    ("06-04-26 00:00:00", date(2026, 4, 6)),
])
def test_parse_erp_date_day_first(text, expected):
    assert parse_erp_date(text) == expected


def test_parse_erp_date_month_first_misread():
    misread = datetime(2026, 6, 4)  # Excel read '06-04-26' as 4 Jun
    assert parse_erp_date(misread, raw_text="06-04-26") == date(2026, 4, 6)
    assert parse_erp_date(misread, swap_misread=True) == date(2026, 4, 6)
    assert parse_erp_date(misread) == date(2026, 6, 4)  # no evidence -> trusted
    assert parse_erp_date(date(2026, 6, 25), swap_misread=True) == date(2026, 6, 25)  # cannot be misread


@pytest.mark.parametrize("bad", ["31-02-26", "hello", "", None, 12345])
def test_parse_erp_date_rejects_garbage(bad):
    with pytest.raises(RuleError):
        parse_erp_date(bad)


# ---- Tolerance edges -----------------------------------------------------------------------

def test_wastage_exact_edges():
    assert wastage_flag(1150, 1000) is False      # 15.00% passes
    assert wastage_flag(1150.1, 1000) is True     # 15.01% flags
    assert wastage_flag(900, 1000) is False       # under-use is not wastage
    assert wastage(900, 1000).metres == -100.0


@given(st.decimals(min_value=Decimal("1.00"), max_value=Decimal("100000.00"), places=2))
def test_wastage_tolerance_property(required):
    assert wastage_flag(required * Decimal("1.15"), required) is False
    assert wastage_flag(required * Decimal("1.1501"), required) is True
    assert wastage_flag(required * Decimal("1.12"), required, wastage_tol="0.12") is False


# ---- Press-only printed totals -------------------------------------------------------------

class _Run:
    def __init__(self, machine_type, printed_qty):
        self.machine_type, self.printed_qty = machine_type, printed_qty


def test_printed_totals_ignore_offline_machines():
    runs = [
        {"machine_type": "press", "printed_qty": 30_000},
        {"machine_type": "Press", "printed_qty": 21_000},
        {"machine_type": "slitter", "printed_qty": 50_000},
        {"machine_type": "die_cutting", "printed_qty": 50_000},
        _Run("press", 1_000),
        _Run("sorting", 9_999),
        {"machine_type": None, "printed_qty": 5},
    ]
    assert printed_total_press_only(runs) == 52_000


# ---- Input guards --------------------------------------------------------------------------

def test_input_guards():
    for call in (
        lambda: ups(0, 2),
        lambda: required_metres(100, 0, 250),
        lambda: required_metres(100, 4, 0),
        lambda: wastage(10, 0),
        lambda: wastage_flag(10, 0),
        lambda: oee(1.1, 0.9, 0.9),
        lambda: machine_hour_rate(1, 1, 0),
        lambda: crew_cost(-1, 800),
        lambda: metres_to_sqm(10, 0),
        lambda: slit_trim_pct(0, [1]),
        lambda: slit_trim_pct(100, [60, 50]),
        lambda: ink_pool_allocation(-1, {"A": 1}),
        lambda: ink_pool_allocation(1, {"A": -1}),
        lambda: required_metres(True, 4, 250),
        lambda: ratio(1, 0),
    ):
        with pytest.raises(RuleError):
            call()
