"""Store rules: stock, UOM, GRN rate check, slitting trim, ink pooling, job-card guard (SPEC 2)."""
from __future__ import annotations

import re
from collections.abc import Collection, Iterable, Mapping
from decimal import Decimal
from typing import Union

from .errors import Number, RuleError, dec, money, over_tolerance, ratio
from .settings import DEFAULTS

JOB_CARD_RE = re.compile(r"^JC-\d{4,}$")

Amounts = Union[Number, Iterable[Number]]


def _total(values: Amounts) -> Decimal:
    if isinstance(values, (int, float, Decimal, str)):
        return dec(values)
    return sum((dec(v) for v in values), Decimal(0))


def stock_balance(opening: Number, received: Amounts, issued: Amounts) -> Decimal:
    """Stock = opening (as of ``stock_from``) + received - issued (SPEC 2, bullet 2).

    ``received``/``issued`` may be a single number or an iterable of movements;
    callers pass only movements dated on/after ``stock_from``. A negative result is
    returned (it is a data-quality signal, not an error).
    """
    return dec(opening) + _total(received) - _total(issued)


def metres_to_sqm(metres: Number, width_mm: Number) -> float:
    """UOM conversion: sq m = metres * width_mm / 1000 (SPEC 2, bullet 2)."""
    if dec(width_mm) <= 0:
        raise RuleError("width must be positive")
    return float((dec(metres) * dec(width_mm) / 1000).quantize(Decimal("0.01")))


def grn_rate_flag(grn_rate: Number, item_rate: Number,
                  grn_rate_tol: Number = DEFAULTS.grn_rate_tol) -> bool:
    """GRN rate flag if the GRN rate differs from the item master rate by > grn_rate_tol (SPEC 2, bullet 4).

    Two-sided. An item without a master rate (0) always flags so it gets a rate.
    """
    if dec(item_rate) == 0:
        return True
    return over_tolerance(ratio(dec(grn_rate) - dec(item_rate), item_rate), grn_rate_tol)


def slit_trim_pct(jumbo_width_mm: Number, output_widths_mm: Iterable[Number]) -> float:
    """Slitting trim % = (jumbo width - sum of slit widths) / jumbo width (SPEC 2, bullet 4)."""
    jumbo = dec(jumbo_width_mm)
    if jumbo <= 0:
        raise RuleError("jumbo width must be positive")
    used = _total(list(output_widths_mm))
    if used > jumbo:
        raise RuleError("slit widths exceed the jumbo width")
    return float(ratio(jumbo - used, jumbo))


def slit_trim_flag(jumbo_width_mm: Number, output_widths_mm: Iterable[Number],
                   slit_tol: Number = DEFAULTS.slit_tol) -> bool:
    """Slitting trim flag if trim % > slit_tol (default 0.05); equal passes (SPEC 2, bullet 4)."""
    return dec(slit_trim_pct(jumbo_width_mm, output_widths_mm)) > dec(slit_tol)


def ink_flag(actual: Number, estimate: Number, ink_tol: Number = DEFAULTS.ink_tol) -> bool:
    """Ink flag if actual vs estimated ink differs by > ink_tol (default 0.20) (SPEC 2, bullet 4)."""
    if dec(estimate) == 0:
        return dec(actual) != 0
    return over_tolerance(ratio(dec(actual) - dec(estimate), estimate), ink_tol)


def ink_pool_allocation(pool_amount: Number, estimates: Mapping[str, Number]) -> dict[str, Decimal]:
    """Share a month's pooled (no job card) ink to jobs in proportion to estimated ink (SPEC 2, bullet 10).

    Shares are rounded to 2 decimals; the rounding remainder goes to the job with the
    largest estimate (first in input order on ties) so shares sum exactly to the pool.
    If no job has a positive estimate, every job gets 0 and the pool stays unallocated.
    """
    pool = money(pool_amount)
    if pool < 0:
        raise RuleError("pool amount must not be negative")
    weights = {job: dec(v) for job, v in estimates.items()}
    if any(w < 0 for w in weights.values()):
        raise RuleError("ink estimates must not be negative")
    total = sum(weights.values(), Decimal(0))
    if total == 0:
        return {job: Decimal("0.00") for job in weights}
    shares = {job: money(pool * w / total) for job, w in weights.items()}
    remainder = pool - sum(shares.values(), Decimal(0))
    if remainder:
        biggest = max(weights, key=lambda j: weights[j])
        shares[biggest] += remainder
    return shares


def require_job_card(job_card: str | None, valid_job_cards: Collection[str] | None = None) -> str:
    """A store issue must carry a valid job card ``JC-####`` (SPEC 2, bullet 7; else 400).

    Raises RuleError when blank, malformed, or not in ``valid_job_cards`` (if given).
    Returns the cleaned job card.
    """
    jc = (job_card or "").strip().upper()
    if not jc:
        raise RuleError("store issue needs a job card")
    if not JOB_CARD_RE.match(jc):
        raise RuleError(f"invalid job card '{job_card}'")
    if valid_job_cards is not None and jc not in valid_job_cards:
        raise RuleError(f"unknown job card '{jc}'")
    return jc
