"""Payables, cash plan, P&L: creditors, payments, cashplan, pnl (SPEC 3 Money). Issue #17 (A3).

Rules (SPEC 2): supplier bill due = bill date + min(credit days, msme_days) for MSME vendors,
else + credit days; a payment clears the oldest bill first (FIFO, ``core.rules.money.fifo_allocate``).
Money above the vendor's open bills is kept as ``unallocated`` (an advance).
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.audit import audit, next_id
from app.deps import DB, Role, T, allow, bad_request
from app.serialize import now
from app.services import cashplan as cash_svc
from app.services import payables as ap_svc
from app.services import pnl as pnl_svc
from core.rules import money as M
from core.rules.errors import RuleError

router = APIRouter()

ROLES = ("owner", "accounts")  # x-roles of every endpoint here


class PaymentCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    vendor_id: str
    date: dt.date
    amount: float
    mode: Literal["neft", "rtgs", "cheque", "upi"]
    ref: str | None = None


@router.get("/creditors", dependencies=[allow(*ROLES)])
def get_creditors(db: DB) -> dict:
    return ap_svc.creditors(db)


@router.post("/payments", status_code=201, dependencies=[allow(*ROLES)])
def post_payment(body: PaymentCreate, db: DB, role: Role) -> dict:
    vendor_id = body.vendor_id.strip()
    vn = T("vendors")
    if not vendor_id or db.execute(select(vn.c.id).where(vn.c.id == vendor_id)).first() is None:
        raise bad_request(f"unknown vendor {vendor_id or '(empty)'}")
    amount = M.money(Decimal(str(body.amount)))
    if amount <= 0:  # fifo_allocate only rejects negative totals; zero is not a payment either
        raise bad_request("amount must be greater than 0")
    try:
        allocs, unallocated = ap_svc.plan_payment(db, vendor_id, amount)
    except RuleError as exc:
        raise bad_request(str(exc)) from exc

    pay_id = next_id(db, "payments", "PAY", 4)
    stamp = now()
    row = {"id": pay_id, "vendor_id": vendor_id, "date": body.date, "amount": amount, "mode": body.mode,
           "ref": (body.ref or "").strip(), "is_demo": False, "created_at": stamp, "updated_at": stamp}
    p, pa = T("payments"), T("payment_allocations")
    db.execute(p.insert().values({k: v for k, v in row.items() if k in p.c}))
    for a in allocs:
        db.execute(pa.insert().values({k: v for k, v in {
            "payment_id": pay_id, "bill_id": a["bill_id"], "applied": a["applied"], "is_demo": False,
            "created_at": stamp, "updated_at": stamp}.items() if k in pa.c}))
    audit(db, role=role, action="payment_create", entity="payments", entity_id=pay_id,
          after={**row, "allocations": [{"bill_id": a["bill_id"], "applied": a["applied"]} for a in allocs],
                 "unallocated": unallocated})
    db.commit()

    out = ap_svc.payment_dict(db, pay_id)
    # balance_after as planned (FIFO over the balances at payment time)
    planned = {a["bill_id"]: float(a["balance_after"]) for a in allocs}
    for a in out["allocations"]:
        a["balance_after"] = planned.get(a["bill_id"], a["balance_after"])
    out["unallocated"] = float(unallocated)
    return out


@router.get("/cashplan", dependencies=[allow(*ROLES)])
def get_cashplan(db: DB) -> dict:
    return cash_svc.cashplan(db)


@router.get("/pnl", dependencies=[allow(*ROLES)])
def get_pnl(db: DB, month: str | None = None) -> dict:
    month = (month or "").strip() or pnl_svc.default_month()
    try:
        return pnl_svc.pnl(db, month)
    except RuleError as exc:
        raise bad_request(str(exc)) from exc
