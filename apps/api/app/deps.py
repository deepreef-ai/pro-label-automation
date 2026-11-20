"""Shared FastAPI dependencies: demo roles, DB session, table lookup and the demo clock.

Roles (SPEC 1): header ``X-Role``; a missing header means ``owner``; an unknown role is
refused like any role that is not allowed. A refused call is 403
``{"detail": "forbidden for role <r>"}``.

Every route declares its allowed roles with ``dependencies=[allow(...)]``, copied from
the operation's ``x-roles`` in ``contract/openapi.yaml``. Route-level dependencies run
before the request body is validated, so a forbidden caller gets 403 even with a bad body.
"""
from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import date
from typing import Annotated

from fastapi import Depends, Header, HTTPException
from sqlalchemy import Table
from sqlalchemy.orm import Session

from core.db import Base, get_session

ROLES = ("owner", "ppic", "design", "store", "production", "qc", "dispatch", "accounts", "marketing")
ALL = ROLES

# The demo story is anchored on this day (contract/README.md); override with DEMO_TODAY=YYYY-MM-DD.
DEMO_TODAY = date(2026, 11, 20)


def today() -> date:
    raw = os.environ.get("DEMO_TODAY")
    return date.fromisoformat(raw) if raw else DEMO_TODAY


def forbidden(role: str) -> HTTPException:
    return HTTPException(status_code=403, detail=f"forbidden for role {role}")


def current_role(x_role: str | None = Header(default=None, alias="X-Role")) -> str:
    """The caller's demo role. Missing header = owner; unknown role = 403."""
    role = (x_role or "owner").strip().lower() or "owner"
    if role not in ROLES:
        raise forbidden(role)
    return role


def allow(*roles: str):
    """Route dependency: ``@router.get(..., dependencies=[allow("owner", "ppic")])``."""
    unknown = set(roles) - set(ROLES)
    if unknown:  # pragma: no cover - programming error
        raise ValueError(f"unknown roles {sorted(unknown)}")
    allowed = frozenset(roles) | {"owner"}

    def check(role: str = Depends(current_role)) -> str:
        if role not in allowed:
            raise forbidden(role)
        return role

    return Depends(check)


def get_db() -> Iterator[Session]:
    """One SQLAlchemy session per request (``core.db``; URL from ``DATABASE_URL``)."""
    yield from get_session()


# Use these in route signatures (ruff B008 forbids ``= Depends(...)`` defaults):
#   def route(db: DB, role: Role) -> dict: ...
DB = Annotated[Session, Depends(get_db)]
Role = Annotated[str, Depends(current_role)]


def T(name: str) -> Table:
    """A table from ``core.models`` by its ``contract/schema.md`` name, e.g. ``T("jobs")``."""
    from core import models  # noqa: F401  (registers every table on Base.metadata)

    try:
        return Base.metadata.tables[name]
    except KeyError:  # pragma: no cover - programming error
        raise RuntimeError(f"table {name!r} is not defined in core.models") from None


def not_found(what: str, ident: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"{what} {ident} not found")


def bad_request(msg: str) -> HTTPException:
    return HTTPException(status_code=400, detail=msg)


def conflict(msg: str) -> HTTPException:
    return HTTPException(status_code=409, detail=msg)
