"""Jobs (PPIC) endpoints (SPEC 3, issue #15): job register, one job, create job card,
PO PDF -> draft, planning material summary. ``GET /api/jobs/{job_card}/360`` lives elsewhere (#17).
"""
from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, File, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from app.audit import audit, next_id
from app.deps import ALL, DB, Role, T, allow, bad_request, conflict, not_found, today
from app.services import jobs as svc
from app.services.clients import client_lock
from app.services.po_reader import PoReadError, read_po
from core.rules.errors import RuleError, dec, ratio
from core.rules.money import po_value
from core.rules.store import JOB_CARD_RE

router = APIRouter()

MAX_PDF_BYTES = 10 * 1024 * 1024


class JobCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    client_id: str = Field(min_length=1)
    po_no: str = Field(min_length=1)
    po_date: date
    product: str = Field(min_length=1)
    label_size: str = Field(min_length=1)
    order_qty: int = Field(gt=0)
    rate: float = Field(ge=0)
    item_id: str = Field(min_length=1)
    machine_id: str | None = None
    ups_across: int = Field(gt=0)
    ups_along: int = Field(gt=0)
    repeat_mm: float = Field(gt=0)
    units: list[str] = Field(default_factory=list)
    due_date: date
    enquiry_id: str | None = None
    priority: Literal["high", "normal", "low"] = "normal"


@router.get("/jobs", dependencies=[allow(*ALL)])
def get_jobs(db: DB, status: str | None = None, q: str | None = None) -> dict:
    if status is not None and status not in svc.JOB_STATUSES:
        raise bad_request(f"status must be one of {', '.join(svc.JOB_STATUSES)}")
    items = svc.list_jobs(db, status=status or None, q=q)
    return {"total": len(items), "items": items}


@router.get("/jobs/{job_card}", dependencies=[allow(*ALL)])
def get_job(job_card: str, db: DB) -> dict:
    jc = job_card.strip().upper()
    if not JOB_CARD_RE.match(jc):
        raise bad_request(f"invalid job card '{job_card}' (expected JC-####)")
    job = svc.get_job(db, jc)
    if job is None:
        raise not_found("job", jc)
    return job


def _exists(db, table: str, ident: str) -> bool:
    t = T(table)
    return db.execute(select(t.c.id).where(t.c.id == ident)).first() is not None


@router.post("/jobs", status_code=201, dependencies=[allow("ppic")])
def post_job(body: JobCreate, db: DB, role: Role) -> dict:
    jobs, machines, quotes = T("jobs"), T("machines"), T("quotes")
    client_id = body.client_id.strip()
    if not _exists(db, "clients", client_id):
        raise bad_request(f"unknown client {client_id}")
    if not _exists(db, "items", body.item_id):
        raise bad_request(f"unknown item {body.item_id}")
    machine_id = body.machine_id
    if machine_id:
        if not _exists(db, "machines", machine_id):
            raise bad_request(f"unknown machine {machine_id}")
    else:  # not on the draft: first press, PPIC can change it later
        machine_id = db.execute(select(machines.c.id).where(func.lower(machines.c.type) == "press")
                                .order_by(machines.c.id).limit(1)).scalar()
    if body.enquiry_id and not _exists(db, "enquiries", body.enquiry_id):
        raise bad_request(f"unknown enquiry {body.enquiry_id}")
    if body.due_date < body.po_date:
        raise bad_request("due_date is before po_date")

    # One PO can cover several job cards (repeat runs, split deliveries), so po_no is not unique.
    po_no = body.po_no.strip()

    lock = client_lock(db, client_id)
    if lock.get("lock_status") == "locked":
        reason = lock.get("reason") or "unpaid invoice past due + grace"
        raise conflict(f"client {client_id} is LOCKED ({reason}); only the owner can release the lock")

    # Marketing rate check: the PO rate against the won quote of the enquiry.
    quote_id, rate_check = None, None
    if body.enquiry_id:
        q = db.execute(select(quotes.c.id, quotes.c.rate, quotes.c.status)
                       .where(quotes.c.enquiry_id == body.enquiry_id)
                       .order_by((quotes.c.status == "accepted").desc(), quotes.c.date.desc(),
                                 quotes.c.id.desc())).first()
        if q is not None:
            quote_id = q.id
            if q.rate:
                diff = float(ratio(dec(body.rate) - dec(q.rate), q.rate))
                rate_check = {"quote_id": q.id, "quote_rate": float(q.rate), "po_rate": round(body.rate, 2),
                              "diff_pct": diff, "matches": diff == 0}

    try:  # validates ups/repeat through the rules engine before saving
        svc.metres(body.order_qty, body.ups_across, body.ups_along, body.repeat_mm, 0)
        value = float(po_value(body.order_qty, body.rate))
    except RuleError as exc:
        raise bad_request(str(exc)) from exc

    jc = next_id(db, "jobs", "JC", 4, column="job_card")
    row = {
        "job_card": jc, "created_on": today(), "client_id": client_id, "po_no": po_no, "po_date": body.po_date,
        "enquiry_id": body.enquiry_id, "quote_id": quote_id, "product": body.product.strip(),
        "label_size": body.label_size.strip(), "order_qty": body.order_qty, "rate": round(body.rate, 2),
        "item_id": body.item_id, "machine_id": machine_id, "ups_across": body.ups_across,
        "ups_along": body.ups_along, "repeat_mm": body.repeat_mm, "units": body.units,
        "due_date": body.due_date, "priority": body.priority, "status": "planned", "is_demo": False,
    }
    db.execute(jobs.insert().values({k: v for k, v in row.items() if k in jobs.c}))
    reason = None
    if rate_check and not rate_check["matches"]:
        reason = (f"PO rate {rate_check['po_rate']:.2f} differs from quote {rate_check['quote_id']} "
                  f"rate {rate_check['quote_rate']:.2f}")
    audit(db, role=role, action="job_create", entity="job", entity_id=jc,
          after={**row, "po_value": value, "rate_check": rate_check}, reason=reason)
    db.commit()
    return svc.get_job(db, jc) or {}


@router.post("/jobs/from-po", dependencies=[allow("ppic", "marketing")])
def post_job_from_po(file: Annotated[UploadFile, File()], db: DB) -> dict:
    data = file.file.read(MAX_PDF_BYTES + 1)
    if len(data) > MAX_PDF_BYTES:
        raise bad_request("PDF is larger than 10 MB")
    try:
        return read_po(db, data, file.filename or "upload.pdf")
    except PoReadError as exc:
        raise bad_request(str(exc)) from exc


@router.get("/planning/material-summary", dependencies=[allow("ppic", "store", "production")])
def get_material_summary(db: DB) -> dict:
    return svc.material_summary(db)
