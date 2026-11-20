"""LOCKED golden numbers for the rules engine (SPEC 2). Do not edit without a [contract] PR."""
from decimal import Decimal

import pytest

from core.rules import DEFAULTS, Defaults
from core.rules.money import admin_share, invoice_amounts, job_profit, po_value, revenue_for_job
from core.rules.production import (
    crew_cost,
    machine_hour_rate,
    material_flag,
    oee,
    overprod_flag,
    planned_metres,
    required_metres,
    ups,
    wastage,
    wastage_flag,
)
from core.rules.store import (
    grn_rate_flag,
    ink_flag,
    ink_pool_allocation,
    metres_to_sqm,
    slit_trim_flag,
    slit_trim_pct,
    stock_balance,
)

# ---- Case A: the client's own demo row -------------------------------------------------

def test_case_a_required_metres_and_po_value():
    u = ups(5, 2)
    assert u == 10
    assert required_metres(10_500, u, 269.9) == pytest.approx(283.4, abs=0.01)
    assert po_value(10_500, "0.75") == Decimal("7875.00")
    assert revenue_for_job(0, po_value(10_500, "0.75")) == Decimal("7875.00")


# ---- Case B: Fresh Juice JC-1301 --------------------------------------------------------

def test_case_b_required_and_wastage():
    req = required_metres(50_000, ups(4, 3), 254)
    assert req == pytest.approx(1058.33, abs=0.01)
    w = wastage(1150, req)
    assert w.metres == pytest.approx(91.67, abs=0.01)
    assert w.pct == pytest.approx(0.0866, abs=0.0005)  # ~8.7%
    assert wastage_flag(1150, req) is False


def test_case_b_planning_adds_ten_percent():
    assert planned_metres(50_000, 12, 254) == pytest.approx(1058.33 * 1.10, abs=0.01)


def test_case_b_machine_costs_and_oee():
    rate = machine_hour_rate(120_000, 40_000, 200)
    assert rate == Decimal("800.00")
    assert crew_cost(3.5, rate) == Decimal("2800.00")
    assert oee(0.75, 0.90, 0.95) == pytest.approx(0.641, abs=0.0005)


def test_case_b_job_profit():
    adm = admin_share(30_000)  # 5% of revenue
    assert adm == Decimal("1500.00")
    p = job_profit(revenue=30_000, material=10_925, plates=2_500, ink=1_900, salaries=2_800,
                   freight=600, admin_share=adm, direct_overhead=350)
    assert p.admin_share + p.direct_overhead == Decimal("1850.00")
    assert p.total_cost == Decimal("20575.00")
    assert p.profit == Decimal("9425.00")
    assert p.margin == Decimal("0.3142")
    assert revenue_for_job(30_000, 7_875) == Decimal("30000.00")  # invoiced wins over PO


def test_case_b_sqm_and_invoice():
    assert metres_to_sqm(1150, 250) == 287.5
    inv = invoice_amounts(50_000, "0.60")
    assert (inv.taxable, inv.gst, inv.total) == (Decimal("30000.00"), Decimal("5400.00"), Decimal("35400.00"))


# ---- Other tolerance flags and store numbers -------------------------------------------

def test_defaults_match_spec():
    assert DEFAULTS == Defaults()
    assert (DEFAULTS.wastage_tol, DEFAULTS.overprod_tol, DEFAULTS.material_tol, DEFAULTS.ink_tol,
            DEFAULTS.slit_tol, DEFAULTS.grn_rate_tol, DEFAULTS.grace_days, DEFAULTS.msme_days,
            DEFAULTS.gst_rate, DEFAULTS.planning_extra, DEFAULTS.admin_pct, DEFAULTS.ai_mode) == (
        0.15, 0.10, 0.03, 0.20, 0.05, 0.05, 15, 45, 0.18, 0.10, 0.05, "cloud")


@pytest.mark.parametrize("printed,flag", [(55_000, False), (55_001, True), (50_000, False)])
def test_overprod_flag(printed, flag):
    assert overprod_flag(printed, 50_000) is flag


@pytest.mark.parametrize("issued,flag", [(1030, False), (970, False), (1031, True), (969, True)])
def test_material_flag_two_sided(issued, flag):
    assert material_flag(issued, 1000) is flag


def test_material_flag_nothing_required():
    assert material_flag(0, 0) is False
    assert material_flag(5, 0) is True


@pytest.mark.parametrize("actual,flag", [(1.2, False), (0.8, False), (1.21, True), (0.79, True)])
def test_ink_flag(actual, flag):
    assert ink_flag(actual, 1.0) is flag
    assert ink_flag(0, 0) is False and ink_flag(1, 0) is True


@pytest.mark.parametrize("grn,flag", [(105, False), (95, False), (105.01, True), (94.99, True)])
def test_grn_rate_flag(grn, flag):
    assert grn_rate_flag(grn, 100) is flag
    assert grn_rate_flag(10, 0) is True


def test_slitting_trim():
    assert slit_trim_pct(1000, [250, 250, 250, 200]) == 0.05
    assert slit_trim_flag(1000, [250, 250, 250, 200]) is False
    assert slit_trim_flag(1000, [250, 250, 250, 199]) is True


def test_stock_balance():
    assert stock_balance(1000, [500, 250], [300]) == Decimal("1450")
    assert stock_balance(100, 0, 150) == Decimal("-50")


def test_ink_pool_allocation_proportional_and_exact():
    shares = ink_pool_allocation(1000, {"JC-1301": 2, "JC-1302": 1, "JC-1303": 0})
    assert shares == {"JC-1301": Decimal("666.67"), "JC-1302": Decimal("333.33"), "JC-1303": Decimal("0.00")}
    shares = ink_pool_allocation(100, {"A": 1, "B": 1, "C": 1})
    assert sum(shares.values()) == Decimal("100.00")
    assert shares["A"] == Decimal("33.34")
    assert ink_pool_allocation(50, {"A": 0}) == {"A": Decimal("0.00")}
