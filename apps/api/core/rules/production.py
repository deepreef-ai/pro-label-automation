"""Production rules: metres, wastage, over-production, OEE and machine costs (SPEC 2)."""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from .errors import Number, RuleError, dec, field, money, over_tolerance, ratio
from .settings import DEFAULTS

PRESS = "press"


def ups(ups_across: int, ups_along: int) -> int:
    """Labels per repeat: ups = ups_across * ups_along (SPEC 2, bullet 1)."""
    if ups_across <= 0 or ups_along <= 0:
        raise RuleError("ups across/along must be positive")
    return int(ups_across) * int(ups_along)


def required_metres(order_qty: Number, total_ups: int, repeat_mm: Number,
                    planning_extra: Number = 0) -> float:
    """Required metres = order_qty / ups * repeat_mm / 1000 (SPEC 2, bullet 1).

    ``planning_extra`` (default 0) adds the planning allowance, e.g. 0.10 for +10%.
    Returned as a float rounded to 2 decimals.
    """
    if total_ups <= 0:
        raise RuleError("ups must be positive")
    if dec(order_qty) < 0 or dec(repeat_mm) <= 0:
        raise RuleError("order qty must be >= 0 and repeat must be positive")
    metres = dec(order_qty) / dec(total_ups) * dec(repeat_mm) / 1000
    metres *= 1 + dec(planning_extra)
    return float(metres.quantize(Decimal("0.01")))


def planned_metres(order_qty: Number, total_ups: int, repeat_mm: Number,
                   planning_extra: Number = DEFAULTS.planning_extra) -> float:
    """Planning metres = required metres + planning extra (default +10%, SPEC 2 bullet 1)."""
    return required_metres(order_qty, total_ups, repeat_mm, planning_extra)


@dataclass(frozen=True)
class Wastage:
    """Wastage in metres and as a fraction of required metres."""

    metres: float
    pct: float


def wastage(used_m: Number, required_m: Number) -> Wastage:
    """Wastage m = used - required; wastage % = wastage / required (SPEC 2, bullet 3).

    The percentage is a fraction rounded to 4 places (0.0866 = 8.66%). Negative
    wastage (used < required) is returned as-is so it can be reviewed.
    """
    if dec(required_m) <= 0:
        raise RuleError("required metres must be positive")
    w = dec(used_m) - dec(required_m)
    return Wastage(metres=float(w.quantize(Decimal("0.01"))), pct=float(ratio(w, required_m)))


def wastage_flag(used_m: Number, required_m: Number,
                 wastage_tol: Number = DEFAULTS.wastage_tol) -> bool:
    """Flag if wastage % > wastage_tol (default 0.15); exactly equal passes (SPEC 2, bullet 3).

    Only over-use flags; the % is compared after rounding to 2 decimal percent.
    """
    if dec(required_m) <= 0:
        raise RuleError("required metres must be positive")
    return ratio(dec(used_m) - dec(required_m), required_m) > dec(wastage_tol)


def overprod_flag(printed_qty: Number, order_qty: Number,
                  overprod_tol: Number = DEFAULTS.overprod_tol) -> bool:
    """Over-production flag if printed > order_qty * (1 + overprod_tol) (SPEC 2, bullet 4)."""
    return dec(printed_qty) > dec(order_qty) * (1 + dec(overprod_tol))


def material_flag(issued_m: Number, required_m: Number,
                  material_tol: Number = DEFAULTS.material_tol) -> bool:
    """Material flag if issued differs from required by more than material_tol (SPEC 2, bullet 4).

    Two-sided: under-issue and over-issue both flag. Nothing required but something
    issued also flags.
    """
    if dec(required_m) == 0:
        return dec(issued_m) != 0
    return over_tolerance(ratio(dec(issued_m) - dec(required_m), required_m), material_tol)


def printed_total_press_only(runs: Iterable[Any]) -> int:
    """Sum printed qty over runs on ``press`` machines only (SPEC 2, bullet 5).

    Each run is a dict or object with ``machine_type`` and ``printed_qty``. Offline
    machines (die cutting, slitting, sorting, rewinding, inspection) are ignored so
    the same labels are not counted twice.
    """
    total = 0
    for run in runs:
        if str(field(run, "machine_type", "")).strip().lower() == PRESS:
            total += int(field(run, "printed_qty", 0) or 0)
    return total


def oee(availability: Number, performance: Number, quality: Number) -> float:
    """OEE = availability * performance * quality, each a 0..1 fraction (SPEC 2, bullet 9)."""
    parts = [dec(availability), dec(performance), dec(quality)]
    if any(p < 0 or p > 1 for p in parts):
        raise RuleError("OEE factors must be between 0 and 1")
    return float((parts[0] * parts[1] * parts[2]).quantize(Decimal("0.0001")))


def machine_hour_rate(crew_salary: Number, other_monthly_cost: Number, hours_run: Number) -> Decimal:
    """Machine hour rate = (crew salary + other monthly cost) / hours run, per machine per month (SPEC 2, bullet 9)."""
    if dec(hours_run) <= 0:
        raise RuleError("hours run must be positive to compute a machine hour rate")
    return money((dec(crew_salary) + dec(other_monthly_cost)) / dec(hours_run))


def crew_cost(hours: Number, rate: Number) -> Decimal:
    """Crew cost = hours * machine hour rate (SPEC 2, bullet 9)."""
    if dec(hours) < 0:
        raise RuleError("hours must not be negative")
    return money(dec(hours) * dec(rate))
