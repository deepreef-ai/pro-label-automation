"""Platform tables (SPEC 6, contract/schema.md): companies and users. Not owned by one company."""
from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, Numeric, UniqueConstraint
from sqlalchemy.orm import mapped_column

from ..db import Base
from ._types import BOOL, DATE, FRAC, ID, INT, NUM, TEXT, TS, Demo, Timestamps


class Company(Demo, Timestamps, Base):
    __tablename__ = "companies"
    id = mapped_column(ID, primary_key=True)                  # CO-###
    name = mapped_column(TEXT, nullable=False)
    slug = mapped_column(TEXT, nullable=False, unique=True)   # web address name
    gstin = mapped_column(TEXT)
    city = mapped_column(TEXT)
    state = mapped_column(TEXT)
    status = mapped_column(TEXT, nullable=False, default="onboarding")  # onboarding|parallel_run|live|paused
    plan = mapped_column(TEXT, nullable=False, default="Demo v0.2")
    ai_budget_month = mapped_column(NUM, nullable=False, default=1000)
    ai_alert_pct = mapped_column(FRAC, nullable=False, default=0.8)
    created_on = mapped_column(DATE, nullable=False)


class User(Demo, Timestamps, Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("company_id", "login", name="uq_users_company_login"),)
    id = mapped_column(ID, primary_key=True)                  # U-#### (unique on the platform)
    company_id = mapped_column(ID, ForeignKey("companies.id"), index=True)  # null = platform_admin
    name = mapped_column(TEXT, nullable=False)
    login = mapped_column(TEXT, nullable=False)               # mobile number or e-mail
    role = mapped_column(TEXT, nullable=False)                # company role or platform_admin
    sign_in = mapped_column(TEXT, nullable=False, default="otp_phone")
    device = mapped_column(TEXT)
    status = mapped_column(TEXT, nullable=False, default="active")  # active|invited|disabled
    last_active_at = mapped_column(TS)


class AiUsage(Timestamps, Base):
    """One AI call made for a company (SPEC 6.4). ``company_id`` is added by ``apply_tenancy``."""

    __tablename__ = "ai_usage"
    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    at = mapped_column(TS, nullable=False)
    month = mapped_column(TEXT, nullable=False, index=True)    # extra: YYYY-MM for fast monthly sums
    purpose = mapped_column(TEXT, nullable=False)              # chat | agent_wording | po_reader
    provider = mapped_column(TEXT, nullable=False)             # provider name or "cache"
    model = mapped_column(TEXT)
    tokens_in = mapped_column(INT, nullable=False, default=0)
    tokens_out = mapped_column(INT, nullable=False, default=0)
    cost = mapped_column(Numeric(14, 4), nullable=False, default=0)  # rupees; 0 for free tiers and cache
    cached = mapped_column(BOOL, nullable=False, default=False)
    calls = mapped_column(INT, nullable=False, default=1)      # extra: >1 only for seeded monthly totals


class AuthSession(Timestamps, Base):
    """A signed-in token (SPEC 6.2). Logout sets ``revoked_at``; a revoked token gets 401."""

    __tablename__ = "sessions"
    id = mapped_column(ID, primary_key=True)                  # token id (jti)
    user_id = mapped_column(ID, ForeignKey("users.id"), nullable=False, index=True)
    company_id = mapped_column(ID, ForeignKey("companies.id"), index=True)  # null = platform_admin
    issued_at = mapped_column(TS, nullable=False)
    expires_at = mapped_column(TS, nullable=False)
    revoked_at = mapped_column(TS)


class OtpCode(Timestamps, Base):
    """One-time password for a login (only a hash is stored)."""

    __tablename__ = "otp_codes"
    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id = mapped_column(ID, ForeignKey("companies.id"), index=True)
    login = mapped_column(TEXT, nullable=False, index=True)
    code_hash = mapped_column(TEXT, nullable=False)
    expires_at = mapped_column(TS, nullable=False)
    attempts = mapped_column(INT, nullable=False, default=0)

