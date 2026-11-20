"""Turn DB rows into contract JSON (SPEC 1: money as numbers with 2 decimals, ISO dates).

``row_dict(row)`` converts a SQLAlchemy ``Row``/mapping: ``Decimal`` -> float, ``date`` ->
``YYYY-MM-DD``, ``datetime`` -> ISO 8601 with offset (naive values are treated as IST,
which is how the demo data is written).
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

IST = timezone(timedelta(hours=5, minutes=30))


def jsonable(v: Any) -> Any:
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, datetime):
        return (v if v.tzinfo else v.replace(tzinfo=IST)).isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, Mapping):
        return {k: jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [jsonable(x) for x in v]
    return v


def money(v: Any) -> float:
    """Rupees: a JSON number rounded to 2 decimals (0.0 for None)."""
    return round(float(v or 0), 2)


def row_dict(row: Any, *, only: Iterable[str] | None = None, drop: Iterable[str] = ()) -> dict:
    m = row._mapping if hasattr(row, "_mapping") else row
    keys = list(only) if only is not None else list(m.keys())
    skip = set(drop)
    return {k: jsonable(m.get(k)) for k in keys if k not in skip}


def now() -> datetime:
    return datetime.now(IST).replace(microsecond=0)
