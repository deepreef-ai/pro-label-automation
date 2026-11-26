"""Platform admin (SPEC 6.3, issue #54 B2): companies, add company, cost & usage.

Platform routes get an unscoped session (``app.deps.PlatformDB``) and read only platform tables with it
(``companies``, ``users``, ``otp_codes``). Anything stored in a company table (AI usage, audit log,
imports) is read **per company through a scoped session** (``core.tenancy.scoped``), so the same code
works under PostgreSQL row-level security (B3 #76).
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, time
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit import audit, next_id
from app.deps import T, conflict, not_found, today
from app.serialize import IST, jsonable, money
from app.services import company_admin
from core.db import SessionLocal
from core.tenancy import scoped

OTP_SMS_RATE = 0.18  # rupees per SMS OTP; e-mail OTP is free

# Shared monthly running cost (rupees), split across companies by active users (screen 20).
SHARED_LINES = (
    ("compute", "App server (cloud, 1 small container)", 4800, "Shared by all companies"),
    ("database", "PostgreSQL database (managed, smallest size)", 2900, "Shared; each row tagged with company_id"),
    ("storage", "File storage and daily backups", 450, "Shared"),
    ("domain", "Domain and SSL certificate", 150, "Shared"),
)
GROWTH_STEPS = (1, 3, 10, 25, 50)
STATUSES = ("onboarding", "parallel_run", "live", "paused")


@contextmanager
def company_session(db: Session, company_id: str, user_id: str | None = None):
    """A session that sees and writes only ``company_id``'s rows (same engine as ``db``)."""
    session = SessionLocal(bind=scoped(db.get_bind(), company_id))
    session.info["user_id"] = user_id if user_id is not None else db.info.get("user_id")
    try:
        yield session
    finally:
        session.close()


def _month_range(month: str) -> tuple[datetime, datetime]:
    y, m = (int(x) for x in month.split("-"))
    start = date(y, m, 1)
    end = date(y + (m == 12), m % 12 + 1, 1)
    return datetime.combine(start, time(), IST), datetime.combine(end, time(), IST)


def current_month() -> str:
    return today().strftime("%Y-%m")


def _companies(db: Session) -> list[dict]:
    companies = T("companies")
    return [dict(r) for r in db.execute(select(companies).order_by(companies.c.id)).mappings()]


def _active_users(db: Session) -> dict[str, int]:
    users = T("users")
    rows = db.execute(select(users.c.company_id, func.count()).where(users.c.status == "active",
                                                                     users.c.company_id.is_not(None))
                      .group_by(users.c.company_id))
    return {cid: n for cid, n in rows}


def _otp_sms(db: Session, month: str) -> dict[str, int]:
    """SMS OTPs sent per company this month (``otp_codes`` is a platform table)."""
    otp = T("otp_codes")
    start, end = _month_range(month)
    out: dict[str, int] = {}
    rows = db.execute(select(otp.c.company_id, otp.c.login).where(otp.c.company_id.is_not(None),
                                                                  otp.c.created_at >= start, otp.c.created_at < end))
    for cid, login in rows:
        if "@" not in (login or ""):
            out[cid] = out.get(cid, 0) + 1
    return out


def _company_activity(db: Session, company_id: str, month: str) -> dict[str, Any]:
    """Per-company counts from company tables, read through a scoped session."""
    start, end = _month_range(month)
    usage, audit_log, imports = T("ai_usage"), T("audit_log"), T("imports")
    with company_session(db, company_id) as s:
        by_purpose = dict(s.execute(select(usage.c.purpose, func.coalesce(func.sum(usage.c.calls), 0))
                                    .where(usage.c.month == month).group_by(usage.c.purpose)).all())
        saves = s.execute(select(func.count()).select_from(audit_log)
                          .where(audit_log.c.at >= start, audit_log.c.at < end)).scalar_one()
        files = s.execute(select(func.count()).select_from(imports)
                          .where(imports.c.at >= start, imports.c.at < end)).scalar_one()
        last_import = s.execute(select(func.max(imports.c.at))).scalar()
    return {"saves": int(saves), "files": int(files), "pos_read": int(by_purpose.get("po_reader", 0)),
            "chats": int(by_purpose.get("chat", 0)), "last_import_at": jsonable(last_import)}


def usage(db: Session, month: str | None = None) -> dict:
    """Contract ``Usage``: cost lines, cost and usage per company, growth estimate."""
    month = month or current_month()
    companies = _companies(db)
    active = _active_users(db)
    otps = _otp_sms(db, month)
    shared_total = sum(line[2] for line in SHARED_LINES)
    total_users = sum(active.get(c["id"], 0) for c in companies)

    rows = []
    for c in companies:
        cid = c["id"]
        st = company_admin.budget_status(db, cid, month)
        act = _company_activity(db, cid, month)
        users = active.get(cid, 0)
        share = users / total_users if total_users else (1 / len(companies))
        shared_cost = money(shared_total * share)
        otp_cost = money(otps.get(cid, 0) * OTP_SMS_RATE)
        direct = money(st["used"] + otp_cost)
        rows.append({
            "company_id": cid, "name": c["name"], "users": users, "saves": act["saves"],
            "pos_read": act["pos_read"], "chats": act["chats"], "files": act["files"], "ai_calls": st["calls"],
            "ai_cost": money(st["used"]), "ai_budget_month": money(c["ai_budget_month"]),
            "ai_used_pct": st["used_pct"], "shared_cost": shared_cost, "direct_cost": direct,
            "total_cost": money(shared_cost + direct),
            # extras for the companies list (not part of CompanyUsage)
            "_otp_cost": otp_cost, "_last_import_at": act["last_import_at"],
        })

    ai_total = money(sum(r["ai_cost"] for r in rows))
    otp_total = money(sum(r["_otp_cost"] for r in rows))
    cost_lines = [{"key": k, "label": label, "basis": "shared", "monthly": amount, "note": note}
                  for k, label, amount, note in SHARED_LINES]
    cost_lines += [
        {"key": "ai", "label": "AI (LLM calls; free tiers first, paid model only when needed)", "basis": "per_use",
         "monthly": ai_total, "note": "Capped per company by its monthly AI budget"},
        {"key": "otp", "label": "Login OTP messages", "basis": "per_use", "monthly": otp_total,
         "note": f"Rs {OTP_SMS_RATE} per SMS; e-mail OTP is free"},
    ]
    direct_avg = sum(r["direct_cost"] for r in rows) / len(rows) if rows else 0.0
    growth = [{"companies": n, "cost_per_company": money(shared_total / n + direct_avg)} for n in GROWTH_STEPS]
    return {
        "month": month, "currency": "INR", "cost_lines": cost_lines,
        "total_cost": money(sum(line["monthly"] for line in cost_lines)),
        "companies": [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows],
        "growth": growth, "is_estimate": True,
        "_rows": rows,
    }


def _company_item(c: dict, u: dict | None) -> dict:
    return {
        "id": c["id"], "name": c["name"], "slug": c["slug"], "city": c["city"], "state": c["state"],
        "status": c["status"], "users": u["users"] if u else 0, "isolation": True,
        "last_import_at": u["_last_import_at"] if u else None,
        "ai_budget_month": money(c["ai_budget_month"]), "ai_used_month": u["ai_cost"] if u else 0.0,
        "ai_used_pct": u["ai_used_pct"] if u else 0.0, "cost_month": u["total_cost"] if u else 0.0,
        "created_on": jsonable(c["created_on"]), "is_demo": bool(c.get("is_demo")),
    }


def list_companies(db: Session) -> dict:
    """Contract ``CompanyList``."""
    use = usage(db)
    by_id = {r["company_id"]: r for r in use["_rows"]}
    items = [_company_item(c, by_id.get(c["id"])) for c in _companies(db)]
    totals = {"companies": len(items), **{s: sum(i["status"] == s for i in items) for s in STATUSES[:3]},
              "users": sum(i["users"] for i in items), "cost_month": use["total_cost"],
              "ai_used_month": money(sum(i["ai_used_month"] for i in items))}
    return {"items": items, "totals": totals}


def get_company(db: Session, company_id: str) -> dict:
    companies = T("companies")
    row = db.execute(select(companies).where(companies.c.id == company_id)).mappings().first()
    if row is None:
        raise not_found("company", company_id)
    return dict(row)


def create_company(db: Session, body: dict, role: str) -> dict:
    """Create the company (status ``onboarding``), its settings row and its first admin (``owner``, invited)."""
    companies = T("companies")
    slug = body["slug"].strip().lower()
    if db.execute(select(companies.c.id).where(companies.c.slug == slug)).first():
        raise conflict(f"slug {slug} is already taken")
    cid = next_id(db, "companies", "CO", 3)
    budget = body.get("ai_budget_month")
    company = {"id": cid, "name": body["name"].strip(), "slug": slug, "city": body.get("city"),
               "state": body.get("state"), "gstin": body.get("gstin"), "status": "onboarding",
               "plan": "Demo v0.2", "ai_budget_month": 1000 if budget is None else budget, "ai_alert_pct": 0.8,
               "created_on": today(), "is_demo": True}
    with company_session(db, cid) as s:
        s.execute(companies.insert().values(**company))
        s.execute(T("settings").insert().values(id=1, company_name=company["name"]))
        admin = company_admin.add_user(s, company_id=cid, name=body["admin_name"], login=body["admin_login"],
                                       role="owner", status="invited")
        audit(s, role=role, action="create_company", entity="companies", entity_id=cid,
              after={**company, "admin_id": admin["id"]})
        s.commit()
    item = _company_item(company, None)
    item["users"] = 1  # the invited first admin (as in platform_company_create.json)
    return {"company": item, "admin": admin, **{k: body.get(k) for k in (
        "name", "slug", "city", "state", "gstin", "admin_name", "admin_login")}, "ai_budget_month": company[
        "ai_budget_month"]}
