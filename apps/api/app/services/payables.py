"""Supplier payables: bills with MSME due dates, FIFO payments (SPEC 2, bullet 14).

All maths goes through ``core.rules.money``: due date = bill date + min(credit days,
``msme_days``) for MSME vendors, else + credit days; a payment clears the oldest bill first
(``fifo_allocate``). ``paid`` on a bill is the sum of its ``payment_allocations`` rows.

``SupplierBill.status``: ``paid`` (balance 0), ``overdue`` (balance left and past due),
``part_paid`` (something paid, not yet due), ``open`` (nothing paid, not yet due).
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.deps import T, today
from core.rules import money as M

DUE_SOON_DAYS = 7  # Creditors.totals.due_7d / msme_due_7d window (today .. today + 7)


def msme_days(db: Session) -> int:
    from app.routers.shell import load_settings  # local import: routers import services

    v = load_settings(db).get("msme_days")
    return int(v) if v is not None else M.DEFAULTS.msme_days


def vendor_rows(db: Session, vendor_ids: Iterable[str] | None = None) -> dict[str, Mapping]:
    vn = T("vendors")
    q = select(vn).order_by(vn.c.id)
    if vendor_ids is not None:
        q = q.where(vn.c.id.in_(list(vendor_ids)))
    return {r._mapping["id"]: r._mapping for r in db.execute(q).all()}


def effective_credit_days(vendor: Mapping, msme: int) -> int:
    """Credit days after the MSME cap (``supplier_due_date`` does not depend on the bill date)."""
    day = today()
    return (M.supplier_due_date(day, int(vendor["credit_days"] or 0), bool(vendor["msme"]), msme) - day).days


def bill_dicts(db: Session, vendor_ids: Iterable[str] | None = None, *, as_of: date | None = None,
               vendors: Mapping[str, Mapping] | None = None) -> list[dict]:
    """Every supplier bill (contract ``SupplierBill`` plus ``vendor_id``/``msme``), oldest first."""
    as_of = as_of or today()
    sb, pa = T("supplier_bills"), T("payment_allocations")
    ids = list(vendor_ids) if vendor_ids is not None else None
    q = select(sb)
    if ids is not None:
        q = q.where(sb.c.vendor_id.in_(ids))
    rows = db.execute(q.order_by(sb.c.date, sb.c.id)).all()
    if not rows:
        return []
    vendors = vendors if vendors is not None else vendor_rows(db, {r._mapping["vendor_id"] for r in rows})
    pq = select(pa.c.bill_id, func.sum(pa.c.applied)).group_by(pa.c.bill_id)
    if ids is not None:
        pq = pq.where(pa.c.bill_id.in_([r._mapping["id"] for r in rows]))
    paid_by_bill = {k: M.money(v or 0) for k, v in db.execute(pq).all()}
    msme = msme_days(db)

    out = []
    for r in rows:
        m = r._mapping
        v = vendors.get(m["vendor_id"])
        credit = int(v["credit_days"] or 0) if v is not None else 0
        is_msme = bool(v["msme"]) if v is not None else False
        amount = M.money(m["amount"] or 0)
        paid = min(paid_by_bill.get(m["id"], Decimal("0.00")), amount)
        balance = max(amount - paid, Decimal("0.00"))
        due = M.supplier_due_date(m["date"], credit, is_msme, msme)
        days_to_due = (due - as_of).days
        if balance <= 0:
            status = "paid"
        elif days_to_due < 0:
            status = "overdue"
        elif paid > 0:
            status = "part_paid"
        else:
            status = "open"
        out.append({
            "id": m["id"], "bill_no": m["bill_no"] or "", "date": m["date"].isoformat(),
            "amount": float(amount), "paid": float(paid), "balance": float(balance),
            "due_date": due.isoformat(), "days_to_due": days_to_due, "status": status,
            "grn_ids": list(m["grn_ids"] or []),
            "vendor_id": m["vendor_id"], "msme": is_msme,
        })
    return out


_BILL_KEYS = ("id", "bill_no", "date", "amount", "paid", "balance", "due_date", "days_to_due", "status", "grn_ids")


def creditors(db: Session) -> dict:
    """``GET /api/creditors``: vendors with open bills (open bills only, oldest first) and totals."""
    as_of = today()
    vendors = vendor_rows(db)
    msme = msme_days(db)
    by_vendor: dict[str, list[dict]] = defaultdict(list)
    for b in bill_dicts(db, as_of=as_of, vendors=vendors):
        if b["balance"] > 0:
            by_vendor[b["vendor_id"]].append(b)

    zero = Decimal("0.00")
    totals = {"outstanding": zero, "overdue": zero, "due_7d": zero, "msme_due_7d": zero}
    rows = []
    for vid, v in vendors.items():
        bills = by_vendor.get(vid)
        if not bills:
            continue
        outstanding = sum((Decimal(str(b["balance"])) for b in bills), zero)
        for b in bills:
            bal = Decimal(str(b["balance"]))
            totals["outstanding"] += bal
            if b["days_to_due"] < 0:
                totals["overdue"] += bal
            elif b["days_to_due"] <= DUE_SOON_DAYS:
                totals["due_7d"] += bal
                if b["msme"]:
                    totals["msme_due_7d"] += bal
        rows.append({
            "vendor_id": vid, "vendor_name": v["name"] or "", "msme": bool(v["msme"]),
            "credit_days": int(v["credit_days"] or 0), "effective_credit_days": effective_credit_days(v, msme),
            "outstanding": float(outstanding), "next_due_date": min(b["due_date"] for b in bills),
            "bills": [{k: b[k] for k in _BILL_KEYS} for b in bills],
        })
    return {"as_of": as_of.isoformat(), "totals": {k: float(v) for k, v in totals.items()}, "vendors": rows}


def plan_payment(db: Session, vendor_id: str, amount: Any) -> tuple[list[dict], Decimal]:
    """FIFO split of ``amount`` over the vendor's open bills.

    Returns ``([{bill_id, bill_no, applied, balance_after}], unallocated)`` for bills that get
    money (oldest first). ``fifo_allocate`` raises ``RuleError`` for a negative amount; callers
    reject amounts <= 0 before calling.
    """
    open_bills = [b for b in bill_dicts(db, [vendor_id]) if b["balance"] > 0]
    rule_bills = [M.Bill(b["id"], date.fromisoformat(b["date"]), Decimal(str(b["balance"]))) for b in open_bills]
    applied = M.fifo_allocate(amount, rule_bills)
    allocs = []
    for b in sorted(open_bills, key=lambda x: x["date"]):  # same stable order as fifo_allocate
        got = applied.get(b["id"], Decimal("0.00"))
        if got > 0:
            allocs.append({"bill_id": b["id"], "bill_no": b["bill_no"], "applied": got,
                           "balance_after": M.money(Decimal(str(b["balance"])) - got)})
    total = sum((a["applied"] for a in allocs), Decimal("0.00"))
    return allocs, max(M.money(amount) - total, Decimal("0.00"))


def payment_dict(db: Session, payment_id: str) -> dict | None:
    """Contract ``Payment`` for a stored payment (allocations with the bill balance after it)."""
    p, pa, sb, vn = T("payments"), T("payment_allocations"), T("supplier_bills"), T("vendors")
    row = db.execute(select(p, vn.c.name.label("vendor_name")).join(vn, vn.c.id == p.c.vendor_id, isouter=True)
                     .where(p.c.id == payment_id)).first()
    if row is None:
        return None
    m = row._mapping
    allocs = db.execute(select(pa.c.bill_id, pa.c.applied, sb.c.bill_no, sb.c.date, sb.c.amount)
                        .join(sb, sb.c.id == pa.c.bill_id).where(pa.c.payment_id == payment_id)
                        .order_by(sb.c.date, sb.c.id)).all()
    # balance after this payment = bill amount - everything applied by this and earlier payments
    out_allocs = []
    for a in allocs:
        earlier = db.execute(
            select(func.sum(pa.c.applied)).join(p, p.c.id == pa.c.payment_id)
            .where(pa.c.bill_id == a.bill_id, (p.c.date < m["date"]) | ((p.c.date == m["date"]) & (p.c.id <= m["id"])))
        ).scalar_one()
        out_allocs.append({"bill_id": a.bill_id, "bill_no": a.bill_no or "", "applied": float(M.money(a.applied)),
                           "balance_after": float(max(M.money(a.amount) - M.money(earlier or 0), Decimal("0.00")))})
    applied = sum((Decimal(str(a["applied"])) for a in out_allocs), Decimal("0.00"))
    amount = M.money(m["amount"] or 0)
    return {
        "id": m["id"], "vendor_id": m["vendor_id"], "vendor_name": m["vendor_name"] or "",
        "date": m["date"].isoformat(), "amount": float(amount), "mode": m["mode"] or "", "ref": m["ref"] or "",
        "allocations": out_allocs, "unallocated": float(max(amount - applied, Decimal("0.00"))),
        "is_demo": bool(m["is_demo"]),
    }
