"""Masters: clients, vendors, items, stock heads, opening stock, machines, costs, settings, audit."""
from __future__ import annotations

from sqlalchemy import ForeignKey, Integer
from sqlalchemy.orm import mapped_column

from ..db import Base
from ._types import BOOL, DATE, FRAC, ID, INT, JSONT, LONG, NUM, QTY, TEXT, TS, Demo, Timestamps


class Client(Demo, Timestamps, Base):
    __tablename__ = "clients"
    id = mapped_column(ID, primary_key=True)                  # CL-###
    name = mapped_column(TEXT, nullable=False, index=True)
    gstin = mapped_column(TEXT)
    city = mapped_column(TEXT)
    state = mapped_column(TEXT)
    contact = mapped_column(TEXT)
    phone = mapped_column(TEXT)
    email = mapped_column(TEXT)
    credit_days = mapped_column(INT, nullable=False, default=30)
    credit_limit = mapped_column(NUM)
    active = mapped_column(BOOL, nullable=False, default=True)
    lock_override_until = mapped_column(DATE)                  # owner release valid until


class Vendor(Demo, Timestamps, Base):
    __tablename__ = "vendors"
    id = mapped_column(ID, primary_key=True)                  # VN-###
    name = mapped_column(TEXT, nullable=False, index=True)
    city = mapped_column(TEXT)
    msme = mapped_column(BOOL, nullable=False, default=False)
    credit_days = mapped_column(INT, nullable=False, default=30)
    supplies = mapped_column(TEXT)
    gstin = mapped_column(TEXT)                               # extra: from the Vendor Register


class StockHead(Demo, Timestamps, Base):
    __tablename__ = "stock_heads"
    id = mapped_column(TEXT, primary_key=True)                # e.g. PP-WHITE
    name = mapped_column(TEXT, nullable=False)
    group = mapped_column(TEXT)
    ppic_paper = mapped_column(TEXT)


class Item(Demo, Timestamps, Base):
    __tablename__ = "items"
    id = mapped_column(ID, primary_key=True)                  # IT-####
    name = mapped_column(TEXT, nullable=False, index=True)
    group = mapped_column(TEXT)
    stock_head_id = mapped_column(TEXT, ForeignKey("stock_heads.id"))
    width_mm = mapped_column(INT)
    uom = mapped_column(TEXT, nullable=False)                 # m, kg, sqm, nos
    rate = mapped_column(NUM)
    rate_unit = mapped_column(TEXT)                           # per_sqm, per_kg, per_m, per_nos
    min_stock = mapped_column(QTY)
    vendor_id = mapped_column(ID, ForeignKey("vendors.id"))
    code = mapped_column(TEXT)                                # extra: ERP item code (not unique)


class OpeningStock(Demo, Timestamps, Base):
    __tablename__ = "opening_stock"
    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    # The client's stock statement is per stock head; rows whose head has no item keep item_id null.
    item_id = mapped_column(ID, ForeignKey("items.id"), index=True)
    stock_head_id = mapped_column(TEXT, ForeignKey("stock_heads.id"))   # extra
    as_of = mapped_column(DATE, nullable=False)
    qty = mapped_column(QTY, nullable=False)
    rate = mapped_column(NUM)
    physical_count = mapped_column(QTY)
    uom = mapped_column(TEXT)                                 # extra: UOM of the statement row
    value = mapped_column(NUM)                                # extra: opening value (qty x rate or typed value)


class Machine(Demo, Timestamps, Base):
    __tablename__ = "machines"
    id = mapped_column(ID, primary_key=True)                  # M-##
    name = mapped_column(TEXT, nullable=False)
    type = mapped_column(TEXT, nullable=False)                # press | offline
    units = mapped_column(INT)
    max_speed_mpm = mapped_column(INT)
    web_width_mm = mapped_column(INT)


class MachineCost(Demo, Timestamps, Base):
    __tablename__ = "machine_costs"
    machine_id = mapped_column(ID, ForeignKey("machines.id"), primary_key=True)
    month = mapped_column(TEXT, primary_key=True)  # YYYY-MM
    crew_salary = mapped_column(NUM, nullable=False)
    other_cost = mapped_column(NUM, nullable=False)


class Settings(Timestamps, Base):
    """One wide row (id = 1). Only the owner can PUT."""

    __tablename__ = "settings"
    id = mapped_column(Integer, primary_key=True)
    wastage_tol = mapped_column(FRAC, nullable=False, default=0.15)
    overprod_tol = mapped_column(FRAC, nullable=False, default=0.10)
    material_tol = mapped_column(FRAC, nullable=False, default=0.03)
    ink_tol = mapped_column(FRAC, nullable=False, default=0.20)
    slit_tol = mapped_column(FRAC, nullable=False, default=0.05)
    grn_rate_tol = mapped_column(FRAC, nullable=False, default=0.05)
    grace_days = mapped_column(INT, nullable=False, default=15)
    msme_days = mapped_column(INT, nullable=False, default=45)
    gst_rate = mapped_column(FRAC, nullable=False, default=0.18)
    planning_extra = mapped_column(FRAC, nullable=False, default=0.10)
    admin_pct = mapped_column(FRAC, nullable=False, default=0.05)
    ai_mode = mapped_column(TEXT, nullable=False, default="cloud")
    stock_from = mapped_column(DATE)
    fy_start = mapped_column(DATE)
    company_name = mapped_column(TEXT)
    updated_by = mapped_column(TEXT)
    extra = mapped_column(JSONT)                              # extra: other admin cells (ink gsm, anilox ...)


class AuditLog(Timestamps, Base):
    __tablename__ = "audit_log"
    id = mapped_column(ID, primary_key=True)                  # AUD-#####
    at = mapped_column(TS, nullable=False)
    role = mapped_column(TEXT, nullable=False)
    user_id = mapped_column(TEXT)                             # v0.2: signed-in user (null in demo mode)
    action = mapped_column(TEXT, nullable=False)
    entity = mapped_column(TEXT)
    entity_id = mapped_column(TEXT)
    before = mapped_column(JSONT)
    after = mapped_column(JSONT)
    reason = mapped_column(LONG)


class FixedAsset(Demo, Timestamps, Base):
    """Extra table (not in schema.md): Fixed Assets & Depreciation from 06 Accounts."""

    __tablename__ = "fixed_assets"
    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind = mapped_column(TEXT, nullable=False)               # block, misc_expenditure, addition
    asset_block = mapped_column(TEXT)
    description = mapped_column(TEXT)
    gross_block_opening = mapped_column(NUM)
    acc_dep_opening = mapped_column(NUM)
    net_block_opening = mapped_column(NUM)
    dep_fy2025_26 = mapped_column(NUM)
    dep_rate = mapped_column(FRAC)
    purchase_date = mapped_column(DATE)
    amount = mapped_column(NUM)


class ListValue(Demo, Timestamps, Base):
    """Extra table (not in schema.md): dropdown lists of the client's workbooks."""

    __tablename__ = "lists"
    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    list_name = mapped_column(TEXT, nullable=False, index=True)
    value = mapped_column(TEXT, nullable=False)
    sort_order = mapped_column(INT)
