"""Shared error type and numeric helpers for the rules engine."""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Union

Number = Union[int, float, Decimal, str]

CENT = Decimal("0.01")


class RuleError(ValueError):
    """A business-rule guard was broken (API maps it to 400 or 409)."""


def dec(value: Number) -> Decimal:
    """Convert a number to Decimal via its string form (avoids binary float noise)."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):  # bool is an int subclass; reject it explicitly
        raise RuleError("boolean is not a number")
    return Decimal(str(value))


def money(value: Number) -> Decimal:
    """Round a rupee amount to 2 decimals, half-up (SPEC 1: money has 2 decimals)."""
    return dec(value).quantize(CENT, rounding=ROUND_HALF_UP)


def field(row: Any, name: str, default: Any = None) -> Any:
    """Read ``name`` from a mapping or an object attribute."""
    if isinstance(row, dict):
        return row.get(name, default)
    return getattr(row, name, default)


RATIO_PLACES = Decimal("0.0001")


def ratio(numerator: Number, denominator: Number) -> Decimal:
    """Return numerator/denominator rounded to 4 places (a percentage with 2 decimals).

    Tolerance checks compare this rounded ratio, so 15.00% is exactly 0.1500 and
    passes a 0.15 tolerance while 15.01% (0.1501) flags.
    """
    d = dec(denominator)
    if d == 0:
        raise RuleError("denominator must not be zero")
    return (dec(numerator) / d).quantize(RATIO_PLACES, rounding=ROUND_HALF_UP)


def over_tolerance(diff_ratio: Decimal, tol: Number) -> bool:
    """True when |ratio| is strictly greater than the tolerance (equal passes)."""
    return abs(diff_ratio) > dec(tol)
