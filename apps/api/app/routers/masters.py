"""Masters endpoints (SPEC 3 "Masters"), the owner lock release and global search (SPEC 3 "Shell")."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.audit import audit
from app.deps import ALL, DB, Role, T, allow, bad_request, conflict, not_found, today
from app.routers.shell import load_settings
from app.serialize import IST, jsonable, money, now
from app.services import clients as svc
from app.services import jobs as jobs_svc
from core.rules import money as M
from core.rules import production as P

router = APIRouter()

RELEASE_DAYS = 10  # an owner release stays valid for today + 10 days (fixture release_lock.json)
SEARCH_LIMIT = 8  # results per entity type


# ---------------------------------------------------------------- clients

@router.get("/clients", dependencies=[allow(*ALL)])
def list_clients(db: DB) -> list[dict]:
    cl = T("clients")
    rows = db.execute(select(cl).order_by(cl.c.id)).all()
    locks = svc.client_locks(db)
    return [svc.client_dict(r._mapping, locks[r._mapping["id"]]) for r in rows]


@router.get("/clients/{id}", dependencies=[allow(*ALL)])
def get_client(id: str, db: DB) -> dict:  # noqa: A002 - path parameter name from the contract
    row = svc.get_client_row(db, id)
    if row is None:
        raise not_found("client", id)
    as_of = today()
    grace = int(load_settings(db).get("grace_days") or 15)
    invoices = svc.invoice_dicts(db, [id], as_of=as_of, credit_days={id: row["credit_days"]})
    lock = svc.lock_state(invoices, client_id=id, as_of=as_of, grace_days=grace,
                          override_until=row.get("lock_override_until"))
    return {
        "client": svc.client_dict(row, lock),
        "buckets": svc.ageing(invoices),
        "invoices": invoices,
        "jobs": _client_jobs(db, id),
        "collections": _collections(db, id, row["name"]),
        "lock_log": _lock_log(db, id, lock),
    }


def _collections(db: Session, client_id: str, client_name: str | None) -> list[dict]:
    col = T("collections")
    rows = db.execute(select(col).where(col.c.client_id == client_id)
                      .order_by(col.c.date.desc(), col.c.id.desc())).all()
    out = []
    for r in rows:
        m = r._mapping
        out.append({
            "id": m["id"], "date": jsonable(m["date"]), "client_id": m["client_id"],
            "client_name": client_name or "", "invoice_ids": list(m["invoice_ids"] or []),
            "mode": m["mode"], "contact": m["contact"] or "", "note": m["note"] or "",
            "promise_date": jsonable(m["promise_date"]),
            "promise_amount": money(m["promise_amount"]) if m["promise_amount"] is not None else None,
            "status": m["status"], "next_follow_up": jsonable(m["next_follow_up"]), "by": m["by"] or "",
            "is_demo": bool(m["is_demo"]),
        })
    return out


def _lock_log(db: Session, client_id: str, lock: dict) -> list[dict]:
    """System lock event (when the rule lock began) plus owner releases from ``audit_log``."""
    events: list[dict] = []
    if lock["rule_locked_since"]:
        since = date.fromisoformat(lock["rule_locked_since"])
        events.append({
            "at": datetime(since.year, since.month, since.day, 0, 5, tzinfo=IST).isoformat(),
            "event": "locked", "by": "system",
            "reason": f"{lock['rule_lock_invoice']} unpaid {lock['grace_days'] + 1} days after due date "
                      f"{lock['rule_lock_due']}",
        })
    aud = T("audit_log")
    rows = db.execute(select(aud).where(aud.c.action == "release_lock", aud.c.entity == "client",
                                        aud.c.entity_id == client_id).order_by(aud.c.at, aud.c.id)).all()
    for r in rows:
        m = r._mapping
        events.append({"at": jsonable(m["at"]), "event": "released", "by": m["role"] or "owner",
                       "reason": m["reason"] or ""})
    events.sort(key=lambda e: datetime.fromisoformat(e["at"]))
    return events


# ---------------------------------------------------------------- client jobs (contract Job shape)

def _client_jobs(db: Session, client_id: str) -> list[dict]:
    """Open jobs plus jobs created in the last 30 days, oldest first (as the fixtures).

    Uses the one Job serializer in ``app.services.jobs`` (flags include client_locked).
    """
    since = (today() - timedelta(days=30)).isoformat()
    return [j for j in jobs_svc.list_jobs(db, client_id=client_id)
            if j["status"] not in ("invoiced", "closed") or (j["created_on"] or "") >= since]


# ---------------------------------------------------------------- release lock (owner only)

class ReleaseLockRequest(BaseModel):
    reason: str = Field(min_length=1)


@router.post("/clients/{id}/release-lock", dependencies=[allow("owner")])
def release_lock(id: str, body: ReleaseLockRequest, db: DB, role: Role) -> dict:  # noqa: A002
    reason = body.reason.strip()
    if not reason:
        raise bad_request("reason: a reason is required to release a lock")
    row = svc.get_client_row(db, id)
    if row is None:
        raise not_found("client", id)
    lock = svc.client_lock(db, id)
    if lock["lock_status"] != "locked":
        raise conflict(f"client {id} is not locked")
    valid_until = today() + timedelta(days=RELEASE_DAYS)
    cl = T("clients")
    db.execute(cl.update().where(cl.c.id == id).values(lock_override_until=valid_until))
    released_at = now()
    audit_id = audit(db, role=role, action="release_lock", entity="client", entity_id=id,
                     before={"lock_status": "locked", "lock_override_until": row.get("lock_override_until")},
                     after={"lock_status": "ok", "lock_override_until": valid_until}, reason=reason)
    db.commit()
    after = svc.client_lock(db, id)
    return {
        "client_id": id, "lock_status": after["lock_status"], "released_by": "owner",
        "released_at": released_at.isoformat(), "reason": reason, "valid_until": valid_until.isoformat(),
        "audit_id": audit_id,
    }


# ---------------------------------------------------------------- vendors, items, machines

@router.get("/vendors", dependencies=[allow("owner", "store", "accounts", "ppic")])
def list_vendors(db: DB) -> list[dict]:
    vn, sb, pa = T("vendors"), T("supplier_bills"), T("payment_allocations")
    msme_days = int(load_settings(db).get("msme_days") or 45)
    billed = dict(db.execute(select(sb.c.vendor_id, func.sum(sb.c.amount)).group_by(sb.c.vendor_id)).all())
    paid = dict(db.execute(select(sb.c.vendor_id, func.sum(pa.c.applied))
                           .join(sb, sb.c.id == pa.c.bill_id).group_by(sb.c.vendor_id)).all())
    out = []
    for r in db.execute(select(vn).order_by(vn.c.id)).all():
        m = r._mapping
        credit = int(m["credit_days"] or 0)
        bill_day = today()  # effective credit days do not depend on the bill date
        eff = (M.supplier_due_date(bill_day, credit, bool(m["msme"]), msme_days) - bill_day).days
        owed = M.money(billed.get(m["id"]) or 0) - M.money(paid.get(m["id"]) or 0)
        out.append({
            "id": m["id"], "name": m["name"] or "", "city": m["city"] or "", "msme": bool(m["msme"]),
            "credit_days": credit, "effective_credit_days": eff, "supplies": m["supplies"] or "",
            "outstanding": float(max(owed, Decimal("0.00"))), "is_demo": bool(m["is_demo"]),
        })
    return out


@router.get("/items", dependencies=[allow(*ALL)])
def list_items(db: DB) -> list[dict]:
    it, sh = T("items"), T("stock_heads")
    rows = db.execute(select(it, sh.c.name.label("stock_head_name"))
                      .join(sh, sh.c.id == it.c.stock_head_id, isouter=True).order_by(it.c.id)).all()
    out = []
    for r in rows:
        m = r._mapping
        out.append({
            "id": m["id"], "name": m["name"] or "", "group": m["group"], "stock_head": m["stock_head_name"] or "",
            "width_mm": int(m["width_mm"]) if m["width_mm"] is not None else None, "uom": m["uom"],
            "rate": money(m["rate"]), "rate_unit": m["rate_unit"],
            "min_stock": round(float(m["min_stock"] or 0), 3), "vendor_id": m["vendor_id"],
            "is_demo": bool(m["is_demo"]),
        })
    return out


@router.get("/machines", dependencies=[allow(*ALL)])
def list_machines(db: DB) -> list[dict]:
    """Cost and hour rate for the latest month (up to this month) in which the machine ran."""
    mc, cost, rn = T("machines"), T("machine_costs"), T("runs")
    this_month = today().strftime("%Y-%m")
    hours: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
    for r in db.execute(select(rn.c.machine_id, rn.c.start, rn.c.hours)
                        .where(rn.c.hours.is_not(None), rn.c.start.is_not(None))).all():
        hours[(r.machine_id, r.start.strftime("%Y-%m"))] += Decimal(str(r.hours))
    costs: dict[str, list] = defaultdict(list)
    for r in db.execute(select(cost).where(cost.c.month <= this_month).order_by(cost.c.month.desc())).all():
        costs[r.machine_id].append(r)
    out = []
    for r in db.execute(select(mc).order_by(mc.c.id)).all():
        m = r._mapping
        rows = costs.get(m["id"], [])
        pick = next((c for c in rows if hours.get((m["id"], c.month), 0) > 0), rows[0] if rows else None)
        crew = M.money(pick.crew_salary or 0) if pick else Decimal("0.00")
        other = M.money(pick.other_cost or 0) if pick else Decimal("0.00")
        h = hours.get((m["id"], pick.month), Decimal(0)) if pick else Decimal(0)
        rate = P.machine_hour_rate(crew, other, h) if h > 0 else Decimal("0.00")
        out.append({
            "id": m["id"], "name": m["name"] or "", "type": m["type"], "units": int(m["units"] or 0),
            "max_speed_mpm": int(m["max_speed_mpm"] or 0), "web_width_mm": int(m["web_width_mm"] or 0),
            "crew_salary_month": float(crew), "other_cost_month": float(other),
            "hours_run_month": round(float(h), 2), "hour_rate": float(rate), "is_demo": bool(m["is_demo"]),
        })
    return out


# ---------------------------------------------------------------- global search

def _like(col, q: str):
    return func.lower(col).like(f"%{q.lower()}%")


def _inr(v) -> str:
    """Rs amount with Indian digit grouping, no paise (e.g. Rs 1,00,000)."""
    n = int(round(float(v or 0)))
    s = str(abs(n))
    head, tail = s[:-3], s[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    body = ",".join([*groups, tail]) if groups else tail
    return f"Rs {'-' if n < 0 else ''}{body}"


def _day(d) -> str:
    return f"{d.day} {d.strftime('%b')}" if d else ""


@router.get("/search", dependencies=[allow(*ALL)])
def search(db: DB, q: str | None = None) -> dict:
    text = (q or "").strip()
    if len(text) < 2:
        raise bad_request("q: search text must be at least 2 characters")
    results: list[dict] = []

    def add(type_: str, id_: str, title: str, subtitle: str, link: str) -> None:
        results.append({"type": type_, "id": id_, "title": title, "subtitle": subtitle, "link": link})

    cl = T("clients")
    client_names = dict(db.execute(select(cl.c.id, cl.c.name)).all())

    jb = T("jobs")
    for r in db.execute(select(jb).where(or_(_like(jb.c.job_card, text), _like(jb.c.product, text),
                                             _like(jb.c.po_no, text)))
                        .order_by(jb.c.job_card).limit(SEARCH_LIMIT)).all():
        m = r._mapping
        add("job", m["job_card"], f"{m['job_card']} {client_names.get(m['client_id'], '')}".strip(),
            f"{m['product'] or ''} - {m['status'] or ''}", f"/jobs/{m['job_card']}")

    for r in db.execute(select(cl.c.id, cl.c.name, cl.c.city)
                        .where(or_(_like(cl.c.id, text), _like(cl.c.name, text)))
                        .order_by(cl.c.id).limit(SEARCH_LIMIT)).all():
        add("client", r.id, r.name or r.id, f"{r.id} - {r.city or ''}".rstrip(" -"),
            f"/money?tab=debtors&client={r.id}")

    vn = T("vendors")
    for r in db.execute(select(vn).where(or_(_like(vn.c.id, text), _like(vn.c.name, text)))
                        .order_by(vn.c.id).limit(SEARCH_LIMIT)).all():
        m = r._mapping
        add("vendor", m["id"], m["name"] or m["id"], f"{m['id']} - {m['supplies'] or m['city'] or ''}",
            f"/money?tab=creditors&vendor={m['id']}")

    it = T("items")
    for r in db.execute(select(it).where(or_(_like(it.c.id, text), _like(it.c.name, text)))
                        .order_by(it.c.id).limit(SEARCH_LIMIT)).all():
        m = r._mapping
        add("item", m["id"], m["name"] or m["id"], f"{m['id']} - {m['group'] or ''}",
            f"/store?tab=stock&item={m['id']}")

    en = T("enquiries")
    for r in db.execute(select(en).where(or_(_like(en.c.id, text), _like(en.c.product, text),
                                             _like(en.c.prospect_name, text)))
                        .order_by(en.c.id).limit(SEARCH_LIMIT)).all():
        m = r._mapping
        who = client_names.get(m["client_id"]) or m["prospect_name"] or ""
        add("enquiry", m["id"], f"{m['id']} {who}".strip(), f"{m['product'] or ''} - {m['status'] or ''}",
            f"/marketing?id={m['id']}")

    dc = T("dispatches")
    for r in db.execute(select(dc).where(or_(_like(dc.c.id, text), _like(dc.c.job_card, text)))
                        .order_by(dc.c.id).limit(SEARCH_LIMIT)).all():
        m = r._mapping
        add("dispatch", m["id"], m["id"], f"{m['job_card']} - {int(m['qty'] or 0):,} labels - {_day(m['date'])}",
            f"/dispatch?id={m['id']}")

    inv = T("invoices")
    hits = db.execute(select(inv.c.id).where(or_(_like(inv.c.id, text), _like(inv.c.job_card, text)))
                      .order_by(inv.c.id).limit(SEARCH_LIMIT)).scalars().all()
    if hits:
        for i in svc.invoice_dicts(db, None, as_of=today()):
            if i["id"] in hits:
                due = date.fromisoformat(i["due_date"])
                add("invoice", i["id"], i["id"], f"{i['client_name'] or ''} - {_inr(i['total'])} - due {_day(due)}",
                    f"/money?tab=invoices&id={i['id']}")

    for table, type_, cols, link in (
        ("grns", "grn", ("id", "bill_no"), "/store?tab=grns&id={}"),
        ("rolls", "roll", ("id",), "/store?tab=rolls&id={}"),
        ("plates", "plate", ("id",), "/design?tab=plates&id={}"),
        ("dies", "die", ("id",), "/design?tab=dies&id={}"),
    ):
        t = T(table)
        conds = [_like(t.c[c], text) for c in cols if c in t.c]
        for r in db.execute(select(t).where(or_(*conds)).order_by(t.c.id).limit(SEARCH_LIMIT)).all():
            m = r._mapping
            add(type_, m["id"], m["id"], _subtitle(type_, m), link.format(m["id"]))

    return {"q": text, "results": results}


def _subtitle(type_: str, m) -> str:
    if type_ == "grn":
        return f"{m.get('item_id') or ''} - {_day(m.get('date'))}".strip(" -")
    if type_ == "roll":
        return f"{m.get('item_id') or ''} - {m.get('width_mm') or ''} mm".strip(" -")
    if type_ == "plate":
        return f"{m.get('job_card') or ''}".strip()
    return str(m.get("size") or m.get("name") or "")
