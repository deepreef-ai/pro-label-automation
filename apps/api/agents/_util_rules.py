"""Small text helpers shared by the rule agents (import checker, store, wastage, planning).

Only formatting lives here: every number is computed by ``core.rules`` / the app services
before it reaches these helpers.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from agents.base import AgentContext


def _group_en_in(int_part: str) -> str:
    """'1234567' -> '12,34,567' (Indian lakh/crore grouping)."""
    if len(int_part) <= 3:
        return int_part
    head, tail = int_part[:-3], int_part[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return ",".join(groups) + "," + tail


def num(value: Any, places: int = 0) -> str:
    """Indian-grouped number: num(2584.45, 2) -> '2,584.45'."""
    d = Decimal(str(value or 0)).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    sign = "-" if d < 0 else ""
    text = f"{abs(d):.{places}f}"
    int_part, _, frac = text.partition(".")
    return sign + _group_en_in(int_part) + (f".{frac}" if frac else "")


def inr(value: Any) -> str:
    """Whole rupees: 'Rs 1,86,400'."""
    return f"Rs {num(value, 0)}"


def rate(value: Any) -> str:
    """A unit rate with paise: 'Rs 48.20'."""
    return f"Rs {num(value, 2)}"


def pct(fraction: Any, places: int = 1) -> str:
    """0.18 -> '18.0%'."""
    return f"{float(fraction or 0) * 100:.{places}f}%"


def day(value: date | datetime | str | None) -> str:
    """'2026-11-19' -> '19-Nov'."""
    if value is None:
        return ""
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return value.strftime("%d-%b")


def as_date(value: date | datetime | str | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.fromisoformat(value).date()


def word(ctx: AgentContext, kind: str, facts: dict, fallback: str) -> str:
    """Optional LLM rewording; any failure (or an empty reply) keeps the deterministic text."""
    try:
        out = ctx.word(kind, facts, fallback)
    except Exception:  # noqa: BLE001 - the demo must never break on the LLM
        return fallback
    return out if isinstance(out, str) and out.strip() else fallback


def join_names(names: list[str], limit: int = 3) -> str:
    """['a','b','c','d'] -> 'a, b, c and 1 more'."""
    names = [n for n in names if n]
    if len(names) <= 1:
        return "".join(names)
    if len(names) <= limit:
        return ", ".join(names[:-1]) + " and " + names[-1]
    return ", ".join(names[:limit]) + f" and {len(names) - limit} more"
