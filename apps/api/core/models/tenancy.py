"""Platform tables (SPEC 6, contract/schema.md): companies and users. Not owned by one company."""
from __future__ import annotations

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import mapped_column

from ..db import Base
from ._types import DATE, FRAC, ID, NUM, TEXT, TS, Demo, Timestamps


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
