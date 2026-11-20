"""Marketing endpoints (SPEC 3 "Marketing", issue #15): enquiry register, quotes, won/lost, summary.

Flow: an enquiry starts ``new``; ``POST /quote`` makes ``Q-####`` (same number as the enquiry)
and moves it to ``quoted``; ``POST /status`` closes it as ``won`` or ``lost``. A won enquiry
without a ``job_card`` is PPIC's queue: PPIC opens the job with ``POST /api/jobs``
(``enquiry_id``); this router never creates jobs.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.audit import audit, next_id
from app.deps import DB, Role, T, allow, bad_request, conflict, not_found, today
from app.serialize import now
from app.services import marketing as svc
from core.rules.errors import money as round_money

router = APIRouter()

EnquiryStatus = Literal["new", "quoted", "won", "lost"]
QUOTE_VALID_DAYS = 15
FOLLOW_UP_DAYS = 3


class EnquiryCreate(BaseModel):
    client_id: str | None = None
    client_name: str = Field(min_length=1)
    product: str = Field(min_length=1)
    label_size: str = Field(min_length=1)
    qty: int = Field(gt=0)
    material: str = Field(min_length=1)
    colours: int = Field(ge=0, le=12)
    finish: str | None = None
    source: str | None = None
    assigned_to: str | None = None


class QuoteCreate(BaseModel):
    rate: float = Field(gt=0)
    qty: int | None = Field(None, gt=0)
    valid_until: date | None = None  # contract marks it required; default = date + 15 days
    notes: str | None = None


class EnquiryStatusUpdate(BaseModel):
    status: EnquiryStatus
    reason: str | None = None
    po_no: str | None = None


def _enquiry_row(db, enquiry_id: str):
    e = T("enquiries")
    row = db.execute(select(e).where(e.c.id == enquiry_id)).first()
    if row is None:
        raise not_found("enquiry", enquiry_id)
    return row._mapping


# ---------------------------------------------------------------- enquiries

@router.get("/enquiries", dependencies=[allow("owner", "marketing", "ppic", "accounts")])
def get_enquiries(db: DB, status: EnquiryStatus | None = None) -> list[dict]:
    return svc.list_enquiries(db, status)


@router.post("/enquiries", status_code=201, dependencies=[allow("owner", "marketing")])
def post_enquiry(body: EnquiryCreate, db: DB, role: Role) -> dict:
    source = (body.source or "phone").strip().lower()
    if source not in svc.SOURCES:
        raise bad_request(f"source must be one of {', '.join(svc.SOURCES)}")
    client_id = (body.client_id or "").strip() or None
    if client_id is not None:
        c = T("clients")
        if db.execute(select(c.c.id).where(c.c.id == client_id)).first() is None:
            raise bad_request(f"unknown client {client_id}")
    day = today()
    tbl = T("enquiries")
    enq_id = next_id(db, "enquiries", "ENQ", 4)
    row = {
        "id": enq_id, "date": day, "client_id": client_id,
        "prospect_name": None if client_id else body.client_name.strip(),
        "product": body.product.strip(), "label_size": body.label_size.strip(),
        "material": body.material.strip(), "finish": (body.finish or "").strip() or "None",
        "qty": body.qty, "colours": body.colours, "source": source,
        "assigned_to": (body.assigned_to or "").strip() or "Unassigned",
        "status": "new", "lost_reason": None, "follow_up_on": day + timedelta(days=FOLLOW_UP_DAYS),
        "is_demo": True, "created_at": now(), "updated_at": now(),
    }
    db.execute(tbl.insert().values({k: v for k, v in row.items() if k in tbl.c}))
    audit(db, role=role, action="enquiry_create", entity="enquiries", entity_id=enq_id, after=row)
    db.commit()
    return svc.get_enquiry(db, enq_id)


# ---------------------------------------------------------------- quotes

@router.post("/enquiries/{id}/quote", status_code=201, dependencies=[allow("owner", "marketing")])
def post_quote(id: str, body: QuoteCreate, db: DB, role: Role) -> dict:
    enq = _enquiry_row(db, id)
    if enq["status"] in ("won", "lost"):
        raise conflict(f"enquiry {id} is already {enq['status']}")
    if enq["status"] == "quoted":
        raise conflict(f"enquiry {id} is already quoted")
    day = today()
    valid_until = body.valid_until or day + timedelta(days=QUOTE_VALID_DAYS)
    if valid_until < day:
        raise bad_request("valid_until must not be before the quote date")
    qty = body.qty or int(enq["qty"] or 0)
    if qty <= 0:
        raise bad_request("qty must be greater than 0")
    num = id.split("-", 1)[1] if id.startswith("ENQ-") else None
    q = T("quotes")
    quote_id = f"Q-{num}" if num else next_id(db, "quotes", "Q", 4)
    if db.execute(select(q.c.id).where(q.c.id == quote_id)).first() is not None:
        raise conflict(f"quote {quote_id} already exists")
    rate = round_money(Decimal(str(body.rate)))
    cost = round_money(svc.quote_value(qty, rate) * svc.cost_ratio(db))
    row = {
        "id": quote_id, "enquiry_id": id, "date": day, "valid_until": valid_until, "qty": qty,
        "rate": rate, "cost_estimate": cost, "notes": (body.notes or "").strip(), "status": "sent",
        "is_demo": True, "created_at": now(), "updated_at": now(),
    }
    db.execute(q.insert().values({k: v for k, v in row.items() if k in q.c}))
    e = T("enquiries")
    follow = day + timedelta(days=FOLLOW_UP_DAYS)
    db.execute(e.update().where(e.c.id == id).values(status="quoted", follow_up_on=follow, updated_at=now()))
    audit(db, role=role, action="quote_create", entity="quotes", entity_id=quote_id, after=row)
    audit(db, role=role, action="enquiry_status", entity="enquiries", entity_id=id,
          before={"status": enq["status"]}, after={"status": "quoted", "quote_id": quote_id})
    db.commit()
    return svc.quote_json(db.execute(select(q).where(q.c.id == quote_id)).one())


# ---------------------------------------------------------------- won / lost

@router.post("/enquiries/{id}/status", dependencies=[allow("owner", "marketing")])
def post_status(id: str, body: EnquiryStatusUpdate, db: DB, role: Role) -> dict:
    enq = _enquiry_row(db, id)
    current, target = enq["status"], body.status
    if current == target:
        raise conflict(f"enquiry {id} is already {current}")
    if current in ("won", "lost"):
        raise conflict(f"enquiry {id} is already {current}; it cannot change to {target}")
    if target == "quoted":
        raise conflict(f"create a quote with POST /api/enquiries/{id}/quote to mark it quoted")
    if target == "new":
        raise conflict(f"enquiry {id} is {current}; it cannot go back to new")
    if target == "won" and current != "quoted":
        raise conflict(f"enquiry {id} has no quote; quote it before marking it won")

    e, q = T("enquiries"), T("quotes")
    reason = (body.reason or "").strip() or None
    values = {"status": target, "follow_up_on": None, "updated_at": now()}
    if target == "lost":
        values["lost_reason"] = reason
    db.execute(e.update().where(e.c.id == id).values({k: v for k, v in values.items() if k in e.c}))
    quote_status = "accepted" if target == "won" else "rejected"
    db.execute(q.update().where(q.c.enquiry_id == id, q.c.status == "sent").values(status=quote_status))
    after = {"status": target, "lost_reason": values.get("lost_reason")}
    if body.po_no:
        after["po_no"] = body.po_no.strip()  # no PO column on enquiries; PPIC enters it on the job card
    audit(db, role=role, action="enquiry_status", entity="enquiries", entity_id=id,
          before={"status": current, "lost_reason": enq["lost_reason"]}, after=after, reason=reason)
    db.commit()
    return svc.get_enquiry(db, id)


# ---------------------------------------------------------------- summary

@router.get("/marketing/summary", dependencies=[allow("owner", "marketing", "ppic", "accounts")])
def get_summary(db: DB) -> dict:
    return svc.summary(db)
