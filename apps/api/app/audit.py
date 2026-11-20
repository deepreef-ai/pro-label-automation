"""Audit log and permanent ID allocation (schema.md: audit_log; SPEC 1: IDs).

Every write calls :func:`audit` inside the same session before ``db.commit()``.
"""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.deps import T
from app.serialize import jsonable, now


def next_id(db: Session, table: str, prefix: str, width: int, column: str = "id") -> str:
    """Next permanent id like ``ENQ-0046``: one above the highest existing number for ``prefix``.

    Ids are never reused or renumbered (SPEC 1).
    """
    col = T(table).c[column]
    pat = re.compile(rf"^{re.escape(prefix)}-(\d+)$")
    best = 0
    for (value,) in db.execute(select(col).where(col.like(f"{prefix}-%"))):
        m = pat.match(value or "")
        if m:
            best = max(best, int(m.group(1)))
    return f"{prefix}-{best + 1:0{width}d}"


def audit(
    db: Session,
    *,
    role: str,
    action: str,
    entity: str,
    entity_id: str,
    before: dict | None = None,
    after: dict | None = None,
    reason: str | None = None,
) -> str:
    """Add one ``audit_log`` row (who, what, when, old -> new). Returns its ``AUD-#####`` id."""
    tbl = T("audit_log")
    aud_id = next_id(db, "audit_log", "AUD", 5)
    row: dict[str, Any] = {
        "id": aud_id,
        "at": now(),
        "role": role,
        "action": action,
        "entity": entity,
        "entity_id": str(entity_id),
        "before": jsonable(before) if before is not None else None,
        "after": jsonable(after) if after is not None else None,
        "reason": reason,
    }
    db.execute(tbl.insert().values({k: v for k, v in row.items() if k in tbl.c}))
    return aud_id


def count(db: Session, table: str, *where) -> int:
    return db.execute(select(func.count()).select_from(T(table)).where(*where)).scalar_one()
