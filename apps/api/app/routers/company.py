"""Company admin routes (SPEC 6.2/6.3, contract tag Company; issue #54 B2). The company owner only."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.deps import DB, Me, allow
from app.services import company_admin as svc

router = APIRouter(tags=["Company"])

CompanyRole = Literal["owner", "ppic", "design", "store", "production", "qc", "dispatch", "accounts", "marketing"]


class UserInvite(BaseModel):
    name: str = Field(min_length=2)
    login: str = Field(min_length=3)
    role: CompanyRole


class UserUpdate(BaseModel):
    role: CompanyRole | None = None
    status: Literal["active", "disabled"] | None = None


@router.get("/company/profile", dependencies=[allow()])
def get_company_profile(db: DB, me: Me) -> dict:
    return svc.profile(db, me)


@router.get("/company/users", dependencies=[allow()])
def get_company_users(db: DB, me: Me) -> dict:
    return svc.list_users(db, me)


@router.post("/company/users", status_code=201, dependencies=[allow()])
def post_company_users(body: UserInvite, db: DB, me: Me) -> dict:
    return svc.invite_user(db, me, body.name, body.login, body.role)


@router.put("/company/users/{id}", dependencies=[allow()])
def put_company_user(id: str, body: UserUpdate, db: DB, me: Me) -> dict:  # noqa: A002
    return svc.update_user(db, me, id, body.role, body.status)


@router.get("/company/connections", dependencies=[allow()])
def get_company_connections(db: DB) -> dict:
    return svc.connections(db)
