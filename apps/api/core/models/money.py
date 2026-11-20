"""Dispatch and money tables (contract/schema.md)."""
from __future__ import annotations

from sqlalchemy import ForeignKey
from sqlalchemy.orm import mapped_column

from ..db import Base
from ._types import DATE, FRAC, ID, INT, JSONT, LONG, NUM, TEXT, TS, Demo, Timestamps


class Dispatch(Demo, Timestamps, Base):
    __tablename__ = "dispatches"
    id = mapped_column(ID, primary_key=True)                  # DC-####
    date = mapped_column(DATE, nullable=False, index=True)
    job_card = mapped_column(ID, ForeignKey("jobs.job_card"), nullable=False, index=True)
    qty = mapped_column(INT, nullable=False)
    boxes = mapped_column(INT)
    vehicle_no = mapped_column(TEXT)
    transporter = mapped_column(TEXT)
    lr_no = mapped_column(TEXT)
    freight = mapped_column(NUM)


class Invoice(Demo, Timestamps, Base):
    __tablename__ = "invoices"
    id = mapped_column(ID, primary_key=True)                  # INV-####
    date = mapped_column(DATE, nullable=False, index=True)
    client_id = mapped_column(ID, ForeignKey("clients.id"), nullable=False, index=True)
    # Null only for opening balances imported from the Opening Debtors sheet (source = "opening").
    job_card = mapped_column(ID, ForeignKey("jobs.job_card"), index=True)
    dispatch_id = mapped_column(ID, ForeignKey("dispatches.id"), unique=True)
    qty = mapped_column(INT, nullable=False)
    rate = mapped_column(NUM, nullable=False)
    gst_rate = mapped_column(FRAC, nullable=False)
    status = mapped_column(TEXT, nullable=False, default="open")   # draft | open
    source = mapped_column(TEXT, nullable=False, default="app")    # extra: app | opening
    ref = mapped_column(TEXT)                                 # extra: original invoice number


class Receipt(Demo, Timestamps, Base):
    __tablename__ = "receipts"
    id = mapped_column(ID, primary_key=True)                  # RCP-####
    date = mapped_column(DATE, nullable=False)
    client_id = mapped_column(ID, ForeignKey("clients.id"), nullable=False, index=True)
    invoice_id = mapped_column(ID, ForeignKey("invoices.id"), nullable=False, index=True)
    amount = mapped_column(NUM, nullable=False)
    mode = mapped_column(TEXT)
    ref = mapped_column(TEXT)


class Collection(Demo, Timestamps, Base):
    __tablename__ = "collections"
    id = mapped_column(ID, primary_key=True)                  # COL-####
    date = mapped_column(DATE, nullable=False)
    client_id = mapped_column(ID, ForeignKey("clients.id"), nullable=False, index=True)
    invoice_ids = mapped_column(JSONT)
    mode = mapped_column(TEXT)
    contact = mapped_column(TEXT)
    note = mapped_column(LONG)
    promise_date = mapped_column(DATE)
    promise_amount = mapped_column(NUM)
    status = mapped_column(TEXT, nullable=False, default="open")
    next_follow_up = mapped_column(DATE)
    by = mapped_column(TEXT)


class SupplierBill(Demo, Timestamps, Base):
    __tablename__ = "supplier_bills"
    id = mapped_column(ID, primary_key=True)                  # SB-####
    vendor_id = mapped_column(ID, ForeignKey("vendors.id"), nullable=False, index=True)
    bill_no = mapped_column(TEXT, nullable=False)
    date = mapped_column(DATE, nullable=False)
    amount = mapped_column(NUM, nullable=False)
    grn_ids = mapped_column(JSONT)


class Payment(Demo, Timestamps, Base):
    __tablename__ = "payments"
    id = mapped_column(ID, primary_key=True)                  # PAY-####
    vendor_id = mapped_column(ID, ForeignKey("vendors.id"), nullable=False, index=True)
    date = mapped_column(DATE, nullable=False)
    amount = mapped_column(NUM, nullable=False)
    mode = mapped_column(TEXT)
    ref = mapped_column(TEXT)


class PaymentAllocation(Demo, Timestamps, Base):
    __tablename__ = "payment_allocations"
    payment_id = mapped_column(ID, ForeignKey("payments.id"), primary_key=True)
    bill_id = mapped_column(ID, ForeignKey("supplier_bills.id"), primary_key=True)
    applied = mapped_column(NUM, nullable=False)


class TallyPnl(Demo, Timestamps, Base):
    """Monthly P&L from Tally. ``is_demo`` is extra here: real months are imported, Oct-2026 is demo."""

    __tablename__ = "tally_pnl"
    month = mapped_column(TEXT, primary_key=True)             # YYYY-MM
    key = mapped_column(TEXT, primary_key=True)               # revenue, material, plates, ink, ...
    amount = mapped_column(NUM, nullable=False)
    imported_at = mapped_column(TS)
    note = mapped_column(LONG)


__all__ = ["Dispatch", "Invoice", "Receipt", "Collection", "SupplierBill", "Payment",
           "PaymentAllocation", "TallyPnl"]
