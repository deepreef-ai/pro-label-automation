"""Login, tokens and logout (SPEC 6.2, issue #53 B1).

* ``POST /api/auth/otp`` -> a 6-digit code for ``(company_slug, login)``. Until an SMS / e-mail provider
  is configured the code is the demo code ``123456``; it is **shown** in the response only in
  ``AUTH_MODE=demo``. The answer is the same for an unknown login (no account guessing).
* ``POST /api/auth/login`` -> a signed token whose claims are the only source of the current company.
* Token = ``base64url(json claims).base64url(HMAC-SHA256)`` with ``AUTH_SECRET``; claims
  ``{jti, company_id, user_id, role, exp}``. Every request re-checks the session row (logout revokes it),
  the user (disabled = 401) and the company (paused = 401).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import importlib
import json
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from core.db import Base, SessionLocal

log = logging.getLogger("app.auth")

DEMO_OTP = "123456"
OTP_TTL = timedelta(minutes=5)
OTP_MAX_ATTEMPTS = 5
TOKEN_TTL = timedelta(hours=12)
_DEV_SECRET = "pro-labels-demo-secret-change-me"


def _t(name: str):
    importlib.import_module("core.models")  # registers the tables on this core.db's Base
    return Base.metadata.tables[name]


def auth_mode() -> str:
    """``demo`` (default): no token = demo company owner, X-Role works. ``token``: token required."""
    mode = (os.environ.get("AUTH_MODE") or "demo").strip().lower()
    return mode if mode in ("demo", "token") else "demo"


def _secret() -> bytes:
    return (os.environ.get("AUTH_SECRET") or _DEV_SECRET).encode()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(body: str) -> str:
    return _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _hash(company_id: str | None, login: str, code: str) -> str:
    return hmac.new(_secret(), f"{company_id}|{login}|{code}".encode(), hashlib.sha256).hexdigest()


def _norm(login: str) -> str:
    return " ".join((login or "").split()).lower()


def mask(login: str) -> str:
    login = (login or "").strip()
    if "@" in login:
        name, _, domain = login.partition("@")
        return f"{name[:1]}***@{domain}"
    digits = [ch for ch in login if ch.isdigit()]
    return f"+91 xxxxx x{''.join(digits[-4:])}" if digits else "***"


def demo_otp_visible() -> bool:
    return auth_mode() == "demo"


PLATFORM_SLUGS = ("", "platform")  # platform staff sign in with no company (the web sends "platform")


def _slug(slug: str | None) -> str:
    s = (slug or "").strip().lower()
    return "" if s in PLATFORM_SLUGS else s


def _company(db, slug: str):
    companies = _t("companies")
    slug = (slug or "").strip().lower()
    if not slug:
        return None
    return db.execute(select(companies).where(companies.c.slug == slug)).mappings().first()


def _user(db, company_id: str | None, login: str):
    users = _t("users")
    stmt = select(users).where(users.c.company_id.is_(None) if company_id is None
                               else users.c.company_id == company_id)
    for row in db.execute(stmt).mappings():
        if _norm(row["login"]) == _norm(login):
            return row
    return None


def send_otp(company_slug: str, login: str) -> dict:
    """Create a code for the login (if it exists). Always the same answer shape."""
    login = (login or "").strip()
    company_slug = _slug(company_slug)
    channel = "email" if "@" in login else "sms"
    with SessionLocal() as db:
        company = _company(db, company_slug)
        company_id = company["id"] if company else None
        user = _user(db, company_id, login) if (company or not company_slug.strip()) else None
        if user is not None:
            code = DEMO_OTP  # no SMS/e-mail provider yet: the demo code (SPEC 6.2)
            otp = _t("otp_codes")
            db.execute(otp.insert().values(company_id=company_id, login=_norm(login),
                                           code_hash=_hash(company_id, _norm(login), code),
                                           expires_at=_now() + OTP_TTL, attempts=0))
            db.commit()
    return {"sent": True, "channel": channel, "masked_to": mask(login), "expires_in_s": int(OTP_TTL.total_seconds()),
            "demo_otp": DEMO_OTP if demo_otp_visible() else None}


def login(company_slug: str, login_: str, otp_code: str) -> dict | None:
    """Check the OTP and return the session (contract ``AuthSession``), or None (401)."""
    company_slug = _slug(company_slug)
    with SessionLocal() as db:
        company = _company(db, company_slug)
        if company_slug and company is None:
            return None
        if company is not None and company["status"] == "paused":
            return None
        company_id = company["id"] if company else None
        user = _user(db, company_id, login_)
        if user is None or user["status"] == "disabled":
            return None
        otp = _t("otp_codes")
        row = db.execute(select(otp).where(otp.c.login == _norm(login_),
                                           (otp.c.company_id.is_(None) if company_id is None
                                            else otp.c.company_id == company_id))
                         .order_by(otp.c.id.desc())).mappings().first()
        if row is None or _aware(row["expires_at"]) < _now() or row["attempts"] >= OTP_MAX_ATTEMPTS:
            return None
        if not hmac.compare_digest(row["code_hash"], _hash(company_id, _norm(login_), (otp_code or "").strip())):
            db.execute(otp.update().where(otp.c.id == row["id"]).values(attempts=row["attempts"] + 1))
            db.commit()
            return None
        db.execute(otp.delete().where(otp.c.id == row["id"]))  # single use

        now = _now()
        jti = secrets.token_urlsafe(12)
        exp = now + TOKEN_TTL
        db.execute(_t("sessions").insert().values(id=jti, user_id=user["id"], company_id=company_id,
                                                   issued_at=now, expires_at=exp))
        users = _t("users")
        db.execute(users.update().where(users.c.id == user["id"])
                   .values(last_active_at=now, status="active"))
        db.commit()
    claims = {"jti": jti, "company_id": company_id, "user_id": user["id"], "role": user["role"],
              "exp": int(exp.timestamp())}
    body = _b64(json.dumps(claims, separators=(",", ":")).encode())
    return {"token": f"{body}.{_sign(body)}", "token_type": "Bearer", "expires_at": exp.isoformat(),
            "user": user_dict(user), "company": company_ref(company)}


def verify_token(token: str) -> dict | None:
    """Claims of a valid, unexpired, not revoked token for an active user and company; else None."""
    body, _, sig = (token or "").partition(".")
    if not body or not sig or not hmac.compare_digest(sig, _sign(body)):
        return None
    try:
        claims = json.loads(_unb64(body))
    except (ValueError, json.JSONDecodeError):
        return None
    if not isinstance(claims, dict) or int(claims.get("exp", 0)) < int(_now().timestamp()):
        return None
    with SessionLocal() as db:
        sess = db.execute(select(_t("sessions")).where(_t("sessions").c.id == claims.get("jti"))).mappings().first()
        if sess is None or sess["revoked_at"] is not None or sess["user_id"] != claims.get("user_id"):
            return None
        user = db.execute(select(_t("users")).where(_t("users").c.id == claims["user_id"])).mappings().first()
        if user is None or user["status"] == "disabled" or user["company_id"] != claims.get("company_id"):
            return None
        if claims.get("company_id") is not None:
            co = db.execute(select(_t("companies").c.status)
                            .where(_t("companies").c.id == claims["company_id"])).scalar()
            if co is None or co == "paused":
                return None
    return {**claims, "role": user["role"]}  # role changes take effect immediately


def logout(token_id: str | None) -> None:
    if not token_id:
        return
    with SessionLocal() as db:
        db.execute(_t("sessions").update().where(_t("sessions").c.id == token_id).values(revoked_at=_now()))
        db.commit()


def user_dict(user) -> dict:
    return {"id": user["id"], "name": user["name"], "login": user["login"], "role": user["role"]}


def company_ref(company) -> dict | None:
    return {"id": company["id"], "name": company["name"], "slug": company["slug"]} if company else None


def me(caller) -> dict:
    """Contract ``AuthMe`` for a token or a demo caller."""
    users, companies = _t("users"), _t("companies")
    with SessionLocal() as db:
        if caller.user_id:
            user = db.execute(select(users).where(users.c.id == caller.user_id)).mappings().first()
        else:  # demo mode: the first user with this role in the demo company
            stmt = select(users).where(users.c.role == caller.role)
            stmt = stmt.where(users.c.company_id.is_(None) if caller.company_id is None
                              else users.c.company_id == caller.company_id)
            user = db.execute(stmt.order_by(users.c.id)).mappings().first()
        company = None
        if caller.company_id:
            company = db.execute(select(companies).where(companies.c.id == caller.company_id)).mappings().first()
        expires = None
        if caller.token_id:
            expires = db.execute(select(_t("sessions").c.expires_at)
                                 .where(_t("sessions").c.id == caller.token_id)).scalar()
    u = user_dict(user) if user else {"id": "U-DEMO", "name": f"Demo {caller.role}", "login": "demo",
                                      "role": caller.role}
    return {"user": u, "company": company_ref(company), "auth_mode": auth_mode(),
            "expires_at": _aware(expires).isoformat() if expires else None}
