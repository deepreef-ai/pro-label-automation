"""Client money state: invoices with receipts, outstanding, ageing and the credit lock (SPEC 2).

All maths goes through ``core.rules.money``; this module only gathers rows and applies the
owner override (``clients.lock_override_until``, valid up to and including that date).

Lock status (``Client.lock_status`` enum):
- ``locked``  - ``core.rules.money.client_locked`` is true (an unpaid invoice is past
  due + grace_days) and no owner release is valid today;
- ``at_risk`` - not locked, but some unpaid invoice is past its due date;
- ``ok``      - nothing overdue, or an owner release is valid today.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.deps import T, today
from core.rules import money as M

BUCKETS = ("not_due", "1_30", "31_60", "61_90", "90_plus")


def get_client_row(db: Session, client_id: str) -> Mapping | None:
    """The ``clients`` row as a mapping, or None when the id is unknown."""
    tbl = T("clients")
    row = db.execute(select(tbl).where(tbl.c.id == client_id)).first()
    return row._mapping if row is not None else None


def _grace_days(db: Session) -> int:
    from app.routers.shell import load_settings  # local import: routers import this module

    g = load_settings(db).get("grace_days")
    return int(g) if g is not None else 15


def invoice_dicts(db: Session, client_ids: Iterable[str] | None = None, *, as_of: date | None = None,
                  credit_days: Mapping[str, int] | None = None) -> list[dict]:
    """Invoices (contract ``Invoice`` shape) with amounts, receipts, due date, ageing and status.

    ``credit_days`` maps client id -> credit days (looked up when not given).
    Draft invoices keep status ``draft`` and are not counted as outstanding by the callers.
    """
    as_of = as_of or today()
    inv, rcp, cl = T("invoices"), T("receipts"), T("clients")
    q = select(inv, cl.c.name.label("client_name"), cl.c.credit_days.label("client_credit_days")) \
        .join(cl, cl.c.id == inv.c.client_id, isouter=True)
    ids = list(client_ids) if client_ids is not None else None
    if ids is not None:
        q = q.where(inv.c.client_id.in_(ids))
    rows = db.execute(q.order_by(inv.c.date, inv.c.id)).all()
    if not rows:
        return []
    rq = select(rcp.c.invoice_id, func.sum(rcp.c.amount)).group_by(rcp.c.invoice_id)
    if ids is not None:
        rq = rq.where(rcp.c.invoice_id.in_([r._mapping["id"] for r in rows]))
    received = {k: Decimal(str(v or 0)) for k, v in db.execute(rq).all()}

    out = []
    for r in rows:
        m = r._mapping
        cd = (credit_days or {}).get(m["client_id"], m["client_credit_days"])
        gst_rate = m["gst_rate"] if m["gst_rate"] is not None else M.DEFAULTS.gst_rate
        amounts = M.invoice_amounts(m["qty"] or 0, m["rate"] or 0, gst_rate)
        got = M.money(received.get(m["id"], 0))
        outstanding = max(amounts.total - got, Decimal("0.00"))
        due = M.due_date(m["date"], cd if cd is not None else None)
        unpaid = outstanding > 0
        days = max((as_of - due).days, 0) if unpaid else 0
        if (m["status"] or "").lower() == "draft":
            status = "draft"
        elif not unpaid:
            status = "paid"
        elif got > 0:
            status = "part_paid"
        else:
            status = "open"
        out.append({
            "id": m["id"], "date": m["date"].isoformat(), "client_id": m["client_id"],
            "client_name": m["client_name"], "job_card": m["job_card"], "dispatch_id": m["dispatch_id"],
            "qty": int(m["qty"] or 0), "rate": float(m["rate"] or 0), "taxable": float(amounts.taxable),
            "gst_rate": round(float(gst_rate), 4), "gst": float(amounts.gst), "total": float(amounts.total),
            "received": float(got), "outstanding": float(outstanding), "due_date": due.isoformat(),
            "days_past_due": days, "bucket": M.ageing_bucket(due, as_of) if unpaid else "not_due",
            "status": status, "is_demo": bool(m["is_demo"]),
        })
    return out


def _counted(invoices: Iterable[dict]) -> list[dict]:
    """Issued (non-draft) invoices that still have money outstanding."""
    return [i for i in invoices if i["status"] != "draft" and i["outstanding"] > 0]


def lock_state(invoices: Iterable[dict], *, client_id: str, as_of: date, grace_days: int,
               override_until: date | None) -> dict:
    """Lock status of one client from its ``invoice_dicts`` rows (see module docstring)."""
    open_invs = _counted(invoices)
    # Explicit balance: core.rules.money.client_locked treats a row without paid/balance as paid.
    rule_rows = [{"due_date": date.fromisoformat(i["due_date"]), "balance": i["outstanding"]} for i in open_invs]
    rule_locked = M.client_locked(rule_rows, as_of, grace_days)
    overdue = [i for i in open_invs if i["days_past_due"] > 0]
    locking = [i for i in overdue if M.is_locked(date.fromisoformat(i["due_date"]), as_of, False, grace_days)]
    gap = timedelta(days=grace_days + 1)
    oldest = min((i for i in open_invs), key=lambda i: (i["due_date"], i["id"]), default=None)
    first_lock = min(locking, key=lambda i: (i["due_date"], i["id"]), default=None)
    released = override_until is not None and as_of <= override_until

    locks_on = locked_since = reason = None
    if rule_locked and not released:
        status = "locked"
        locked_since = date.fromisoformat(first_lock["due_date"]) + gap
        reason = (f"{first_lock['id']} unpaid {first_lock['days_past_due']} days after due date "
                  f"{first_lock['due_date']}")
    elif rule_locked:  # an owner release is valid today
        status = "ok"
        locks_on = override_until + timedelta(days=1)
        reason = f"released by owner until {override_until.isoformat()}"
    elif overdue:
        status = "at_risk"
        first = min(overdue, key=lambda i: (i["due_date"], i["id"]))
        locks_on = date.fromisoformat(first["due_date"]) + gap
        if released:
            locks_on = max(locks_on, override_until + timedelta(days=1))
        reason = f"{first['id']} overdue {first['days_past_due']} days; locks on {locks_on.isoformat()}"
    else:
        status = "ok"
    return {
        "client_id": client_id,
        "lock_status": status,
        "reason": reason,
        "outstanding": float(sum((Decimal(str(i["outstanding"])) for i in open_invs), Decimal("0.00"))),
        "overdue_amount": float(sum((Decimal(str(i["outstanding"])) for i in overdue), Decimal("0.00"))),
        "oldest_due": oldest["due_date"] if oldest else None,
        "max_days_past_due": max((i["days_past_due"] for i in open_invs), default=0),
        "locks_on": locks_on.isoformat() if locks_on else None,
        "locked_since": locked_since.isoformat() if locked_since else None,
        # When the rule lock started, even if an owner release is active now (for the lock log).
        "rule_locked_since": (date.fromisoformat(first_lock["due_date"]) + gap).isoformat() if first_lock else None,
        "rule_lock_invoice": first_lock["id"] if first_lock else None,
        "rule_lock_due": first_lock["due_date"] if first_lock else None,
        "override_until": override_until.isoformat() if override_until else None,
        "grace_days": grace_days,
        "as_of": as_of.isoformat(),
    }


def client_lock(db: Session, client_id: str) -> dict:
    """Lock state of one client as of ``today()``.

    Returns ``{client_id, lock_status: ok|at_risk|locked, reason, overdue_amount, oldest_due,
    outstanding, max_days_past_due, locks_on, locked_since, override_until, ...}``.
    An unknown client returns ``lock_status "ok"`` with zero amounts.
    """
    row = get_client_row(db, client_id)
    as_of = today()
    grace = _grace_days(db)
    if row is None:
        return lock_state([], client_id=client_id, as_of=as_of, grace_days=grace, override_until=None)
    invs = invoice_dicts(db, [client_id], as_of=as_of, credit_days={client_id: row["credit_days"]})
    return lock_state(invs, client_id=client_id, as_of=as_of, grace_days=grace,
                      override_until=row.get("lock_override_until"))


def client_locks(db: Session, client_ids: Iterable[str] | None = None) -> dict[str, dict]:
    """``client_lock`` for many clients (all when ``client_ids`` is None) with two queries."""
    cl = T("clients")
    q = select(cl.c.id, cl.c.credit_days, cl.c.lock_override_until)
    ids = list(client_ids) if client_ids is not None else None
    if ids is not None:
        q = q.where(cl.c.id.in_(ids))
    clients = db.execute(q).all()
    as_of, grace = today(), _grace_days(db)
    by_client: dict[str, list[dict]] = defaultdict(list)
    for inv in invoice_dicts(db, ids, as_of=as_of, credit_days={c.id: c.credit_days for c in clients}):
        by_client[inv["client_id"]].append(inv)
    return {c.id: lock_state(by_client[c.id], client_id=c.id, as_of=as_of, grace_days=grace,
                             override_until=c.lock_override_until) for c in clients}


def ageing(invoices: Iterable[dict]) -> dict[str, float]:
    """Outstanding by ageing bucket (issued invoices only)."""
    totals = {b: Decimal("0.00") for b in BUCKETS}
    for i in _counted(invoices):
        totals[i["bucket"]] += Decimal(str(i["outstanding"]))
    return {b: float(v) for b, v in totals.items()}


def client_dict(row: Mapping[str, Any], lock: dict) -> dict:
    """Contract ``Client`` from a clients row and its lock state."""
    return {
        "id": row["id"], "name": row["name"] or "", "gstin": row["gstin"] or "", "city": row["city"] or "",
        "state": row["state"] or "", "contact": row["contact"] or "", "phone": row["phone"] or "",
        "email": row["email"] or "", "credit_days": int(row["credit_days"] if row["credit_days"] is not None else 30),
        "credit_limit": round(float(row["credit_limit"] or 0), 2),
        "outstanding": lock["outstanding"], "overdue": lock["overdue_amount"],
        "lock_status": lock["lock_status"], "locks_on": lock["locks_on"], "locked_since": lock["locked_since"],
        "is_demo": bool(row["is_demo"]),
    }
