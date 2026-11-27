"""QC and dispatch guards (SPEC 2, bullets 6-7)."""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .errors import RuleError, field

EXCLUDED_DECISIONS = frozenset({"hold", "rework", "rejected"})


def qc_validate(printed: int, checked: int, approved: int, rejected: int) -> None:
    """QC entry guard: approved + rejected == checked and checked <= printed (SPEC 2, bullet 6).

    Raises RuleError on any broken rule (API: 400). Negative quantities are rejected.
    """
    if min(printed, checked, approved, rejected) < 0:
        raise RuleError("QC quantities must not be negative")
    if approved + rejected != checked:
        raise RuleError(f"approved ({approved}) + rejected ({rejected}) must equal checked ({checked})")
    if checked > printed:
        raise RuleError(f"checked ({checked}) cannot exceed printed ({printed})")


def counts_as_approved(decision: Any) -> bool:
    """A QC row counts as approved unless its decision is Hold, Rework or Rejected (SPEC 2, bullet 6)."""
    return str(decision or "").strip().lower() not in EXCLUDED_DECISIONS


def approved_total(rows: Iterable[Any]) -> int:
    """Total QC-approved qty for a job, skipping Hold/Rework/Rejected rows (SPEC 2, bullet 6).

    Rows are dicts/objects with ``approved_qty`` and ``decision`` (case-insensitive).
    """
    return sum(int(field(r, "approved_qty", 0) or 0) for r in rows
               if counts_as_approved(field(r, "decision")))


def dispatch_allowed(approved: int, already_dispatched: int, new_qty: int) -> bool:
    """True when cumulative dispatched (already + new) <= QC approved (SPEC 2, bullet 7). Equal is allowed."""
    if new_qty <= 0:
        return False
    return already_dispatched + new_qty <= approved


def check_dispatch(approved: int, already_dispatched: int, new_qty: int) -> int:
    """Dispatch guard: raise RuleError (API: 409) if cumulative dispatch would exceed QC approved (SPEC 2, bullet 7).

    Returns the new cumulative dispatched qty.
    """
    if new_qty <= 0:
        raise RuleError("dispatch qty must be positive")
    if not dispatch_allowed(approved, already_dispatched, new_qty):
        raise RuleError(
            f"dispatch of {new_qty} would make {already_dispatched + new_qty}, above QC approved {approved}")
    return already_dispatched + new_qty
