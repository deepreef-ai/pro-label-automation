"""Platform admin routes (SPEC 6.3, contract tag Platform; issue #54 B2). ``platform_admin`` only."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, Query, UploadFile
from pydantic import BaseModel, Field

from app.deps import Me, PlatformDB, allow_platform, bad_request
from app.services import onboarding
from app.services import platform as svc

router = APIRouter(tags=["Platform"])

MAX_XLSX_BYTES = 20 * 1024 * 1024


class CompanyCreate(BaseModel):
    name: str = Field(min_length=2)
    slug: str = Field(pattern=r"^[a-z0-9-]{3,30}$")
    city: str | None = None
    state: str | None = None
    gstin: str | None = None
    admin_name: str = Field(min_length=1)
    admin_login: str = Field(min_length=3)
    ai_budget_month: float | None = Field(default=None, ge=0)


@router.get("/platform/companies", dependencies=[allow_platform()])
def get_platform_companies(db: PlatformDB) -> dict:
    return svc.list_companies(db)


@router.post("/platform/companies", status_code=201, dependencies=[allow_platform()])
def post_platform_companies(body: CompanyCreate, db: PlatformDB, me: Me) -> dict:
    return svc.create_company(db, body.model_dump(), me.role)


@router.post("/platform/companies/{id}/import", dependencies=[allow_platform()])
def post_platform_company_import(id: str, file: Annotated[UploadFile, File()], db: PlatformDB, me: Me) -> dict:  # noqa: A002
    company = svc.get_company(db, id)
    data = file.file.read(MAX_XLSX_BYTES + 1)
    if len(data) > MAX_XLSX_BYTES:
        raise bad_request("file is larger than 20 MB")
    name = file.filename or "onboarding_template.xlsx"
    if not name.lower().endswith(".xlsx"):
        raise bad_request("file must be the onboarding template (.xlsx)")
    # good rows go in through a session that sees and writes only this company
    with svc.company_session(db, company["id"], me.user_id) as s:
        return onboarding.run_import(s, company["id"], name, data, me.role)


@router.get("/platform/usage", dependencies=[allow_platform()])
def get_platform_usage(db: PlatformDB, month: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}$")] = None) -> dict:
    if month is not None and not 1 <= int(month[5:]) <= 12:
        raise bad_request("month must be YYYY-MM")
    out = svc.usage(db, month)
    out.pop("_rows", None)
    return out
