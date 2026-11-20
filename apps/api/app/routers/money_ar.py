"""Receivables: invoices, debtors, collections (SPEC 3 Money). Issue #17 (A3).

The owner lock release (``POST /api/clients/{id}/release-lock``) lives in ``routers/masters.py``.
"""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from app.deps import DB, Role, allow
from app.services import receivables as svc

router = APIRouter()


@router.get("/invoices", dependencies=[allow("owner", "accounts")])
def get_invoices(db: DB, status: str | None = None, client_id: str | None = None) -> dict:
    return svc.list_invoices(db, status=status, client_id=client_id)


@router.post("/invoices/draft-from-dispatch/{dispatch_id}", status_code=201,
             dependencies=[allow("owner", "accounts")])
def post_invoice_draft(dispatch_id: str, db: DB, role: Role) -> dict:
    return svc.draft_from_dispatch(db, dispatch_id, role)


@router.get("/debtors", dependencies=[allow("owner", "accounts", "marketing")])
def get_debtors(db: DB) -> dict:
    return svc.debtors(db)


class CollectionCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    date: dt.date
    client_id: str = Field(min_length=1)
    invoice_ids: list[str] = Field(default_factory=list)
    mode: str = Field(min_length=1)
    contact: str = ""
    note: str = Field(min_length=1)
    promise_date: dt.date | None = None
    promise_amount: float | None = Field(None, ge=0)
    next_follow_up: dt.date | None = None


@router.get("/collections", dependencies=[allow("owner", "accounts", "marketing")])
def get_collections(db: DB) -> list[dict]:
    return svc.list_collections(db)


@router.post("/collections", status_code=201, dependencies=[allow("owner", "accounts", "marketing")])
def post_collection(body: CollectionCreate, db: DB, role: Role) -> dict:
    return svc.create_collection(db, body.model_dump(), role)
