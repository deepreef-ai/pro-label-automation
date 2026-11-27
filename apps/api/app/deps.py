"""Shared FastAPI dependencies: caller (token or demo role), company-scoped DB session, table lookup
and the demo clock.

v0.2 (SPEC 6.2): ``Authorization: Bearer <token>`` sets the company, user and role; ``AUTH_MODE=token``
requires it (401 otherwise). In ``AUTH_MODE=demo`` (default) a call without a token is the demo
company (``CO-001``) with the ``X-Role`` role, exactly as in v0.1.

Roles (SPEC 1): header ``X-Role``; a missing header means ``owner``; an unknown role is
refused like any role that is not allowed. A refused call is 403
``{"detail": "forbidden for role <r>"}``.

Every route declares its allowed roles with ``dependencies=[allow(...)]``, copied from
the operation's ``x-roles`` in ``contract/openapi.yaml``. Route-level dependencies run
before the request body is validated, so a forbidden caller gets 403 even with a bad body.
"""
from __future__ import annotations

import importlib
import os
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from typing import Annotated

from fastapi import Depends, Header, HTTPException
from sqlalchemy import Table
from sqlalchemy.orm import Session

from app.services import auth as _auth
from core.db import Base, SessionLocal, get_session
from core.tenancy import default_company

auth_mode = _auth.auth_mode

ROLES = ("owner", "ppic", "design", "store", "production", "qc", "dispatch", "accounts", "marketing")
ALL = ROLES

# The demo story is anchored on this day (contract/README.md); override with DEMO_TODAY=YYYY-MM-DD.
DEMO_TODAY = date(2026, 11, 20)


def today() -> date:
    raw = os.environ.get("DEMO_TODAY")
    return date.fromisoformat(raw) if raw else DEMO_TODAY


def forbidden(role: str) -> HTTPException:
    return HTTPException(status_code=403, detail=f"forbidden for role {role}")


def unauthorized(msg: str = "not signed in") -> HTTPException:
    return HTTPException(status_code=401, detail=msg)


PLATFORM_ADMIN = "platform_admin"


@dataclass(frozen=True)
class Caller:
    """Who is calling (SPEC 6.2). The company comes only from the token (or the demo default)."""

    role: str
    company_id: str | None      # None only for platform_admin
    user_id: str | None = None  # None in demo mode without a token
    token_id: str | None = None




def caller(
    authorization: str | None = Header(default=None),
    x_role: str | None = Header(default=None, alias="X-Role"),
) -> Caller:
    """Resolve the caller: a Bearer token always wins over ``X-Role``; a bad token is 401."""
    if authorization is not None:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer":
            raise unauthorized()
        claims = _auth.verify_token(token.strip())
        if claims is None:
            raise unauthorized()
        return Caller(role=claims["role"], company_id=claims["company_id"], user_id=claims["user_id"],
                      token_id=claims["jti"])
    if _auth.auth_mode() == "token":
        raise unauthorized()
    role = (x_role or "owner").strip().lower() or "owner"
    if role == PLATFORM_ADMIN:
        return Caller(role=role, company_id=None)
    if role not in ROLES:
        raise forbidden(role)
    return Caller(role=role, company_id=default_company())


Me = Annotated[Caller, Depends(caller)]


def current_role(c: Me) -> str:
    """The caller's role (token role, or demo ``X-Role``; missing = owner)."""
    return c.role


def allow(*roles: str):
    """Company route: ``dependencies=[allow("owner", "ppic")]``. The owner may always call it;
    ``platform_admin`` never may (platform staff see no company data)."""
    unknown = set(roles) - set(ROLES)
    if unknown:  # pragma: no cover - programming error
        raise ValueError(f"unknown roles {sorted(unknown)}")
    allowed = frozenset(roles) | {"owner"}

    def check(role: str = Depends(current_role)) -> str:
        if role not in allowed:
            raise forbidden(role)
        return role

    return Depends(check)


def allow_platform():
    """Platform route (``/api/platform/*``): ``platform_admin`` only (SPEC 6.2)."""

    def check(role: str = Depends(current_role)) -> str:
        if role != PLATFORM_ADMIN:
            raise forbidden(role)
        return role

    return Depends(check)


def get_db(c: Me) -> Iterator[Session]:
    """One session per request, scoped to the caller's company (``core.tenancy``)."""
    if c.company_id is None:
        raise forbidden(c.role)
    gen = get_session(c.company_id)
    session = next(gen)
    session.info["user_id"] = c.user_id
    try:
        yield session
    finally:
        gen.close()


def get_platform_db(c: Me) -> Iterator[Session]:
    """Unscoped session for platform routes only (sees every company). Platform staff only."""
    if c.role != PLATFORM_ADMIN:
        raise forbidden(c.role)
    session = SessionLocal()
    session.info["user_id"] = c.user_id
    try:
        yield session
    finally:
        session.close()


# Use these in route signatures (ruff B008 forbids ``= Depends(...)`` defaults):
#   def route(db: DB, role: Role) -> dict: ...
DB = Annotated[Session, Depends(get_db)]
Role = Annotated[str, Depends(current_role)]
PlatformDB = Annotated[Session, Depends(get_platform_db)]


def T(name: str) -> Table:
    """A table from ``core.models`` by its ``contract/schema.md`` name, e.g. ``T("jobs")``."""
    # import_module (not ``from core import models``) so a re-imported ``core.db`` gets its
    # tables registered too: the package attribute can still point at an older module.
    importlib.import_module("core.models")
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
