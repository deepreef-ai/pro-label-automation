"""Company admin (SPEC 6.2/6.3, issue #54 B2): the signed-in company's profile, users and connections.

Every function takes the caller's company-scoped session (``app.deps.DB``) and the caller (``Me``).
``companies`` and ``users`` are platform tables, so they are filtered here by the caller's company id;
a user of another company is 404 (never 403).
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit import audit, next_id
from app.deps import Caller, T, conflict, not_found
from app.serialize import jsonable, money
from core.llm.budget import AiBudget

USER_FIELDS = ("id", "name", "login", "role", "device", "sign_in", "last_active_at", "status")

# Default status of each connection until a ``connections`` row says otherwise (screen 19).
CONNECTIONS = (
    ("erp", "ERP (job cards, GRN and issue exports)", "demo",
     "Daily export uploaded by Store; automatic pull every 15 min after go-live"),
    ("tally", "Tally (monthly P&L)", "not_connected",
     "Month-end figures typed by Accounts; direct Tally link planned"),
    ("po_inbox", "PO inbox (client PO e-mails)", "demo",
     "PDFs uploaded on the Jobs screen are read into draft job cards"),
    ("whatsapp", "WhatsApp Business (reminders)", "not_connected",
     "Approved reminders go to the Outbox (simulated); WhatsApp API after approval"),
)


def norm_login(login: str) -> str:
    return " ".join((login or "").split()).lower()


def sign_in_for(login: str) -> str:
    return "otp_email" if "@" in (login or "") else "otp_phone"


def user_dict(row) -> dict:
    return {k: jsonable(row[k]) for k in USER_FIELDS}


def active_users(db: Session, company_id: str) -> int:
    users = T("users")
    return db.execute(select(func.count()).select_from(users)
                      .where(users.c.company_id == company_id, users.c.status == "active")).scalar_one()


def budget_status(db: Session, company_id: str, month: str | None = None) -> dict:
    """AI budget use from ``ai_usage`` (``core.llm.AiBudget``) on this request's database."""
    return AiBudget(db.get_bind()).status(company_id, month)


def profile(db: Session, me: Caller) -> dict:
    companies = T("companies")
    co = db.execute(select(companies).where(companies.c.id == me.company_id)).mappings().first()
    if co is None:
        raise not_found("company", str(me.company_id))
    st = budget_status(db, co["id"])
    return {
        "id": co["id"], "name": co["name"], "slug": co["slug"], "gstin": co["gstin"], "city": co["city"],
        "state": co["state"], "status": co["status"], "plan": co["plan"] or "Demo v0.2",
        "users": active_users(db, co["id"]), "created_on": jsonable(co["created_on"]),
        "ai_budget_month": money(co["ai_budget_month"]), "ai_used_month": money(st["used"]),
        "ai_used_pct": st["used_pct"], "ai_alert_pct": float(co["ai_alert_pct"] if co["ai_alert_pct"] is not None
                                                             else 0.8),
        "ai_over_budget": bool(st["over"]),
    }


def list_users(db: Session, me: Caller) -> dict:
    users = T("users")
    rows = db.execute(select(users).where(users.c.company_id == me.company_id).order_by(users.c.id)).mappings()
    items = [user_dict(r) for r in rows]
    totals = {s: sum(u["status"] == s for u in items) for s in ("active", "invited", "disabled")}
    return {"items": items, "totals": totals}


def _login_taken(db: Session, company_id: str | None, login: str, except_id: str | None = None) -> bool:
    users = T("users")
    stmt = select(users.c.id, users.c.login).where(
        users.c.company_id.is_(None) if company_id is None else users.c.company_id == company_id)
    return any(norm_login(lg) == norm_login(login) and uid != except_id for uid, lg in db.execute(stmt))


def add_user(db: Session, *, company_id: str | None, name: str, login: str, role: str, status: str,
             device: str | None = None) -> dict:
    """Insert a user (global ``U-####`` id). 409 when the login is taken in that company."""
    login = " ".join(login.split())
    if _login_taken(db, company_id, login):
        raise conflict(f"login {login} is already used in this company")
    uid = next_id(db, "users", "U", 4)
    row = {"id": uid, "company_id": company_id, "name": name.strip(), "login": login, "role": role,
           "sign_in": sign_in_for(login), "device": device, "status": status, "last_active_at": None}
    db.execute(T("users").insert().values(**row))
    return {k: row[k] for k in USER_FIELDS}


def invite_user(db: Session, me: Caller, name: str, login: str, role: str) -> dict:
    user = add_user(db, company_id=me.company_id, name=name, login=login, role=role, status="invited")
    audit(db, role=me.role, action="invite_user", entity="users", entity_id=user["id"], after=user)
    db.commit()
    return user


def _is_self(me: Caller, user) -> bool:
    if me.user_id:
        return user["id"] == me.user_id
    # demo mode (no token): the caller is the company's owner
    return user["role"] == "owner"


def update_user(db: Session, me: Caller, user_id: str, role: str | None, status: str | None) -> dict:
    users = T("users")
    row = db.execute(select(users).where(users.c.id == user_id, users.c.company_id == me.company_id)) \
        .mappings().first()
    if row is None:
        raise not_found("user", user_id)
    before = user_dict(row)
    if _is_self(me, row):
        if status == "disabled":
            raise conflict("the owner cannot disable themselves")
        if role is not None and role != "owner":
            raise conflict("the owner cannot remove their own owner role")
    changes: dict = {}
    if role is not None and role != row["role"]:
        changes["role"] = role
    # "active" on an invited user keeps them invited until they first sign in
    if status is not None and status != row["status"] and not (status == "active" and row["status"] == "invited"):
        changes["status"] = status
    if changes:
        db.execute(users.update().where(users.c.id == user_id, users.c.company_id == me.company_id)
                   .values(**changes))
        after = {**before, **changes}
        audit(db, role=me.role, action="update_user", entity="users", entity_id=user_id, before=before,
              after=after)
        db.commit()
        return after
    return before


def connections(db: Session) -> dict:
    tbl = T("connections")
    saved = {r["key"]: r for r in db.execute(select(tbl)).mappings()}  # scoped to the caller's company
    items = []
    for key, label, status, detail in CONNECTIONS:
        r = saved.get(key)
        items.append({
            "key": key, "label": label,
            "status": (r["status"] if r else None) or status,
            "detail": (r["detail"] if r else None) or detail,
            "last_sync_at": jsonable(r["last_sync_at"]) if r else None,
        })
    return {"items": items}
