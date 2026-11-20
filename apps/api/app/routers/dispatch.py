"""dispatch endpoints (SPEC 3). Issue #16 (A2): dispatch register, challans, challan PDF."""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Response
from pydantic import BaseModel, ConfigDict, Field

from app.deps import DB, Role, allow, not_found
from app.routers.shell import load_settings
from app.services import dispatch as svc
from app.services.challan_pdf import render_challan

router = APIRouter()


class DispatchCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    date: dt.date
    job_card: str = Field(min_length=1)
    qty: int = Field(gt=0)
    boxes: int = Field(0, ge=0)
    vehicle_no: str = Field(min_length=1)
    transporter: str = Field(min_length=1)
    freight: float = Field(ge=0)
    lr_no: str = ""


@router.get("/dispatch", dependencies=[allow("dispatch", "qc", "accounts", "ppic")])
def get_dispatch(db: DB) -> list[dict]:
    return svc.list_dispatches(db)


@router.post("/dispatch", status_code=201, dependencies=[allow("dispatch")])
def post_dispatch(body: DispatchCreate, db: DB, role: Role) -> dict:
    return svc.create_dispatch(db, body.model_dump(), role)


@router.get("/dispatch/{id}/challan.pdf", dependencies=[allow("dispatch", "accounts")])
def get_challan_pdf(id: str, db: DB) -> Response:  # noqa: A002 - path name from the contract
    dc_id = id.strip().upper()
    data = svc.challan_data(db, dc_id)
    if data is None:
        raise not_found("dispatch", dc_id)
    company = str(load_settings(db).get("company_name") or "")
    pdf = render_challan(data, company)
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="challan_{dc_id}.pdf"'})
