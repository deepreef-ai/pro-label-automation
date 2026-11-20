"""ERP date parsing, always day-first (SPEC 2, bullet 8).

Behaviour of :func:`parse_erp_date`:

* Text ``dd-mm-yy`` / ``dd-mm-yyyy`` (separators ``-``, ``/`` or ``.``) is read day
  first: ``06-04-26`` -> 6 Apr 2026. Two-digit years are 2000 + yy. ISO
  ``yyyy-mm-dd`` text is also accepted.
* A ``date``/``datetime`` that Excel produced by reading the text month-first (e.g.
  ``06-04-26`` stored as 4 Jun 2026) is corrected by re-parsing ``raw_text`` when the
  original text is available; the raw text always wins.
* Without raw text a date object is trusted as-is, unless ``swap_misread=True``: then
  day and month are swapped (only possible when the day is <= 12; otherwise Excel
  could not have mis-read it and the date is returned unchanged).
* Anything else raises RuleError.
"""
from __future__ import annotations

import re
from datetime import date, datetime

from .errors import RuleError

_DMY = re.compile(r"^(\d{1,2})[-/.](\d{1,2})[-/.](\d{2}|\d{4})$")
_ISO = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")


def _build(y: int, m: int, d: int, text: str) -> date:
    try:
        return date(y, m, d)
    except ValueError as exc:
        raise RuleError(f"invalid date '{text}'") from exc


def _parse_text(text: str) -> date:
    s = text.strip()
    if " " in s:  # drop a time part such as '06-04-26 00:00:00'
        s = s.split(" ", 1)[0]
    m = _ISO.match(s)
    if m:
        return _build(int(m.group(1)), int(m.group(2)), int(m.group(3)), text)
    m = _DMY.match(s)
    if not m:
        raise RuleError(f"unrecognised ERP date '{text}'")
    day, month, year = int(m.group(1)), int(m.group(2)), m.group(3)
    y = 2000 + int(year) if len(year) == 2 else int(year)
    return _build(y, month, day, text)


def parse_erp_date(value: str | date | datetime | None, raw_text: str | None = None,
                   swap_misread: bool = False) -> date:
    """Parse an ERP date day-first and fix Excel's month-first misreads (SPEC 2, bullet 8).

    See the module docstring for the exact behaviour.
    """
    if raw_text is not None and str(raw_text).strip():
        return _parse_text(str(raw_text))
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        if swap_misread and value.day <= 12:
            return _build(value.year, value.day, value.month, str(value))
        return value
    if isinstance(value, str) and value.strip():
        return _parse_text(value)
    raise RuleError(f"cannot parse ERP date {value!r}")
