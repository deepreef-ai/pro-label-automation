"""Store endpoints (SPEC 3, issue #16 A2): summary, live stock, GRNs, issues, rolls, slitting,
party laminate, ink pool allocation and the ERP data-quality report.

Guards (SPEC 2): a store issue must carry a valid job card (400); an issue larger than its roll
balance is 409; a GRN is checked against the item master rate (``rate_flag``).
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from app.audit import audit, next_id
from app.deps import DB, Role, T, allow, bad_request, conflict, not_found, today
from app.services import store as svc
from core.rules import store as S
from core.rules.errors import RuleError, dec

router = APIRouter()

READERS = ("store", "ppic", "production", "accounts")  # + owner (x-roles)
WRITERS = ("store",)
QTY_EPS = Decimal("0.001")


class GrnCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    date: dt.date
    vendor_id: str = Field(min_length=1)
    bill_no: str = Field(min_length=1)
    item_id: str = Field(min_length=1)
    qty: float = Field(gt=0)
    rate: float = Field(ge=0)
    roll_lengths_m: list[float] | None = None


class IssueCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    date: dt.date
    job_card: str | None = None  # required by the contract; checked by core.rules (400 with a clear message)
    item_id: str = Field(min_length=1)
    qty: float = Field(gt=0)
    roll_id: str | None = None
    issued_to: str | None = None


# ---------------------------------------------------------------- reads

@router.get("/store/summary", dependencies=[allow(*READERS)])
def get_summary(db: DB) -> dict:
    return svc.summary(db)


@router.get("/store/stock", dependencies=[allow(*READERS)])
def get_stock(db: DB, group: str | None = None, q: str | None = None) -> dict:
    try:
        return svc.stock(db, group=group, q=q)
    except RuleError as exc:
        raise bad_request(str(exc)) from exc


@router.get("/store/grns", dependencies=[allow(*READERS)])
def get_grns(db: DB) -> list[dict]:
    return svc.list_grns(db)


@router.get("/store/issues", dependencies=[allow(*READERS)])
def get_issues(db: DB, job_card: str | None = None) -> list[dict]:
    jc = (job_card or "").strip()
    if not jc:
        return svc.list_issues(db)
    if jc.lower() == "missing":  # lines without a job card (data-quality link)
        return svc.list_issues(db, missing_jc=True)
    jc = jc.upper()
    if not S.JOB_CARD_RE.match(jc):
        raise bad_request(f"invalid job card '{job_card}' (expected JC-####)")
    return svc.list_issues(db, job_card=jc)


@router.get("/store/rolls", dependencies=[allow(*READERS)])
def get_rolls(db: DB) -> list[dict]:
    return svc.list_rolls(db)


@router.get("/store/slitting", dependencies=[allow(*READERS)])
def get_slitting(db: DB) -> list[dict]:
    return svc.list_slitting(db)


@router.get("/store/party-laminate", dependencies=[allow(*READERS)])
def get_party_laminate(db: DB) -> dict:
    return svc.party_laminate(db)


@router.get("/store/ink-allocation", dependencies=[allow(*READERS)])
def get_ink_allocation(db: DB, month: str | None = None) -> dict:
    m = (month or "").strip() or today().strftime("%Y-%m")
    try:
        return svc.ink_allocation(db, m)
    except RuleError as exc:
        raise bad_request(str(exc)) from exc


@router.get("/store/data-quality", dependencies=[allow(*READERS)])
def get_data_quality(db: DB) -> dict:
    return svc.data_quality(db)


# ---------------------------------------------------------------- writes

def _row(db, table: str, ident: str):
    t = T(table)
    return db.execute(select(t).where(t.c.id == ident)).first()


@router.post("/store/grns", status_code=201, dependencies=[allow(*WRITERS)])
def post_grn(body: GrnCreate, db: DB, role: Role) -> dict:
    grns, rolls = T("grns"), T("rolls")
    vendor_id, item_id, bill_no = body.vendor_id.strip(), body.item_id.strip(), body.bill_no.strip()
    if _row(db, "vendors", vendor_id) is None:
        raise bad_request(f"unknown vendor {vendor_id}")
    item = _row(db, "items", item_id)
    if item is None:
        raise bad_request(f"unknown item {item_id}")
    if body.date > today():
        raise bad_request(f"GRN date {body.date.isoformat()} is in the future")
    dup = db.execute(select(grns.c.id).where(grns.c.vendor_id == vendor_id, grns.c.item_id == item_id,
                                             func.lower(grns.c.bill_no) == bill_no.lower())).first()
    if dup is not None:
        raise bad_request(f"duplicate GRN: bill {bill_no} of {vendor_id} for {item_id} is already {dup.id}")

    is_roll_item = (item.uom or "") == svc.ROLL_UOM
    lengths = [dec(x) for x in (body.roll_lengths_m or [])]
    if lengths and not is_roll_item:
        raise bad_request(f"item {item_id} ({item.uom}) is not kept in rolls; omit roll_lengths_m")
    if any(x <= 0 for x in lengths):
        raise bad_request("every roll length must be positive")
    qty = dec(body.qty)
    if lengths and abs(sum(lengths, Decimal(0)) - qty) > QTY_EPS:
        raise bad_request(f"roll lengths add up to {float(sum(lengths, Decimal(0)))} m, not the GRN qty {body.qty} m")
    if is_roll_item and not lengths:
        lengths = [qty]  # one numbered roll for the whole receipt

    grn_id = next_id(db, "grns", "GRN", 5)
    row = {"id": grn_id, "date": body.date, "vendor_id": vendor_id, "bill_no": bill_no, "item_id": item_id,
           "qty": body.qty, "rate": body.rate, "source": "app", "is_demo": False}
    db.execute(grns.insert().values({k: v for k, v in row.items() if k in grns.c}))
    roll_ids = []
    for length in lengths:
        rid = next_id(db, "rolls", f"R-{body.date.year}", 4)
        db.execute(rolls.insert().values(id=rid, item_id=item_id, width_mm=item.width_mm, length_m=float(length),
                                         source="grn", source_ref=grn_id, received_on=body.date,
                                         location=None, is_demo=False))
        roll_ids.append(rid)
    out = svc.list_grns(db, ids=[grn_id])[0]
    audit(db, role=role, action="grn_create", entity="grns", entity_id=grn_id, after=out,
          reason="rate differs from item rate" if out["rate_flag"] else None)
    db.commit()
    return out


@router.post("/store/issues", status_code=201, dependencies=[allow(*WRITERS)])
def post_issue(body: IssueCreate, db: DB, role: Role) -> dict:
    issues, jobs = T("issues"), T("jobs")
    try:  # SPEC 2: a store issue must carry a valid job card (else 400)
        jc = S.require_job_card(body.job_card)
        if db.execute(select(jobs.c.job_card).where(jobs.c.job_card == jc)).first() is None:
            S.require_job_card(jc, ())
    except RuleError as exc:
        raise bad_request(str(exc)) from exc
    item_id = body.item_id.strip()
    item = _row(db, "items", item_id)
    if item is None:
        raise not_found("item", item_id)
    if body.date > today():
        raise bad_request(f"issue date {body.date.isoformat()} is in the future")
    roll_id = (body.roll_id or "").strip() or None
    if roll_id:
        roll = _row(db, "rolls", roll_id)
        if roll is None:
            raise not_found("roll", roll_id)
        if roll.item_id != item_id:
            raise bad_request(f"roll {roll_id} holds {roll.item_id}, not {item_id}")
        balance = svc.roll_balances(db, [roll_id])[roll_id]["balance"]
        if dec(body.qty) > balance + QTY_EPS:
            raise conflict(f"roll {roll_id} has {float(balance)} m left, less than {body.qty}")

    iss_id = next_id(db, "issues", "ISS", 5)
    row = {"id": iss_id, "date": body.date, "job_card": jc, "item_id": item_id, "qty": body.qty,
           "roll_id": roll_id, "issued_to": (body.issued_to or "").strip() or None, "source": "app",
           "is_demo": False}
    db.execute(issues.insert().values({k: v for k, v in row.items() if k in issues.c}))
    out = svc.list_issues(db, ids=[iss_id])[0]
    audit(db, role=role, action="issue_create", entity="issues", entity_id=iss_id, after=out)
    db.commit()
    return out
