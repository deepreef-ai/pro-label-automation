"""Sales, planning, design, store and production tables (contract/schema.md)."""
from __future__ import annotations

from sqlalchemy import ForeignKey
from sqlalchemy.orm import mapped_column

from ..db import Base
from ._types import DATE, ID, INT, JSONT, LONG, NUM, QTY, TEXT, TS, Demo, Timestamps

# ------------------------------------------------------------------ sales and planning


class Enquiry(Demo, Timestamps, Base):
    __tablename__ = "enquiries"
    id = mapped_column(ID, primary_key=True)                  # ENQ-####
    date = mapped_column(DATE, nullable=False)
    client_id = mapped_column(ID, ForeignKey("clients.id"))
    prospect_name = mapped_column(TEXT)
    product = mapped_column(TEXT)
    label_size = mapped_column(TEXT)
    material = mapped_column(TEXT)
    finish = mapped_column(TEXT)
    qty = mapped_column(INT)
    colours = mapped_column(INT)
    source = mapped_column(TEXT)
    assigned_to = mapped_column(TEXT)
    status = mapped_column(TEXT, nullable=False, default="new")
    lost_reason = mapped_column(TEXT)
    follow_up_on = mapped_column(DATE)


class Quote(Demo, Timestamps, Base):
    __tablename__ = "quotes"
    id = mapped_column(ID, primary_key=True)                  # Q-#### (same number as its enquiry)
    enquiry_id = mapped_column(ID, ForeignKey("enquiries.id"), nullable=False, index=True)
    date = mapped_column(DATE, nullable=False)
    valid_until = mapped_column(DATE)
    qty = mapped_column(INT, nullable=False)
    rate = mapped_column(NUM, nullable=False)
    cost_estimate = mapped_column(NUM)
    notes = mapped_column(LONG)
    status = mapped_column(TEXT, nullable=False, default="sent")


class Job(Demo, Timestamps, Base):
    __tablename__ = "jobs"
    job_card = mapped_column(ID, primary_key=True)            # JC-####
    created_on = mapped_column(DATE, nullable=False)
    client_id = mapped_column(ID, ForeignKey("clients.id"), nullable=False, index=True)
    po_no = mapped_column(TEXT)
    po_date = mapped_column(DATE)
    enquiry_id = mapped_column(ID, ForeignKey("enquiries.id"))
    quote_id = mapped_column(ID, ForeignKey("quotes.id"))
    product = mapped_column(TEXT)
    label_size = mapped_column(TEXT)
    order_qty = mapped_column(INT, nullable=False)
    rate = mapped_column(NUM, nullable=False)
    item_id = mapped_column(ID, ForeignKey("items.id"), nullable=False)
    machine_id = mapped_column(ID, ForeignKey("machines.id"), nullable=False)
    ups_across = mapped_column(INT, nullable=False)
    ups_along = mapped_column(INT, nullable=False)
    repeat_mm = mapped_column(QTY, nullable=False)
    units = mapped_column(JSONT)
    due_date = mapped_column(DATE)
    priority = mapped_column(TEXT, nullable=False, default="normal")
    status = mapped_column(TEXT, nullable=False, default="planned", index=True)


# ------------------------------------------------------------------ design


class Die(Demo, Timestamps, Base):
    __tablename__ = "dies"
    id = mapped_column(ID, primary_key=True)                  # D-###
    type = mapped_column(TEXT)
    label_size = mapped_column(TEXT)
    ups_across = mapped_column(INT)
    ups_along = mapped_column(INT)
    repeat_mm = mapped_column(QTY)
    vendor_id = mapped_column(ID, ForeignKey("vendors.id"))
    cost = mapped_column(NUM)
    made_on = mapped_column(DATE)
    last_job_card = mapped_column(ID, ForeignKey("jobs.job_card"))
    impressions = mapped_column(INT)
    status = mapped_column(TEXT)
    location = mapped_column(TEXT)


class Design(Demo, Timestamps, Base):
    __tablename__ = "design"
    job_card = mapped_column(ID, ForeignKey("jobs.job_card"), primary_key=True)
    stage = mapped_column(TEXT, nullable=False, default="artwork")
    designer = mapped_column(TEXT)
    artwork_version = mapped_column(INT, nullable=False, default=1)
    proof_sent_on = mapped_column(DATE)
    approved_on = mapped_column(DATE)
    approved_by = mapped_column(TEXT)
    die_id = mapped_column(ID, ForeignKey("dies.id"))
    units = mapped_column(JSONT)
    route = mapped_column(JSONT)
    notes = mapped_column(LONG)


class Plate(Demo, Timestamps, Base):
    __tablename__ = "plates"
    id = mapped_column(ID, primary_key=True)                  # PL-#####
    job_card = mapped_column(ID, ForeignKey("jobs.job_card"), nullable=False, index=True)
    unit = mapped_column(INT)
    colour = mapped_column(TEXT)
    made_on = mapped_column(DATE)
    vendor_id = mapped_column(ID, ForeignKey("vendors.id"))
    cost = mapped_column(NUM)
    impressions = mapped_column(INT)
    status = mapped_column(TEXT)
    rack = mapped_column(TEXT)


# ------------------------------------------------------------------ store


class Grn(Demo, Timestamps, Base):
    __tablename__ = "grns"
    id = mapped_column(ID, primary_key=True)                  # GRN-#####
    date = mapped_column(DATE, nullable=False, index=True)
    vendor_id = mapped_column(ID, ForeignKey("vendors.id"))
    bill_no = mapped_column(TEXT)
    item_id = mapped_column(ID, ForeignKey("items.id"), nullable=False, index=True)
    qty = mapped_column(QTY, nullable=False)
    rate = mapped_column(NUM)
    source = mapped_column(TEXT, nullable=False, default="app")   # app | erp_import
    ref = mapped_column(TEXT)                                 # extra: ERP GRN / PO number
    raw_date = mapped_column(TEXT)                            # extra: original ERP date text


class Roll(Demo, Timestamps, Base):
    __tablename__ = "rolls"
    id = mapped_column(ID, primary_key=True)                  # R-YYYY-####
    item_id = mapped_column(ID, ForeignKey("items.id"), nullable=False, index=True)
    width_mm = mapped_column(INT)
    length_m = mapped_column(QTY, nullable=False)
    source = mapped_column(TEXT)                              # grn, slit, opening
    source_ref = mapped_column(TEXT)
    received_on = mapped_column(DATE)
    location = mapped_column(TEXT)


class Issue(Demo, Timestamps, Base):
    __tablename__ = "issues"
    id = mapped_column(ID, primary_key=True)                  # ISS-#####
    date = mapped_column(DATE, nullable=False, index=True)
    job_card = mapped_column(ID, ForeignKey("jobs.job_card"), index=True)  # null only for erp_import
    item_id = mapped_column(ID, ForeignKey("items.id"), nullable=False, index=True)
    qty = mapped_column(QTY, nullable=False)
    roll_id = mapped_column(ID, ForeignKey("rolls.id"))
    issued_to = mapped_column(TEXT)
    source = mapped_column(TEXT, nullable=False, default="app")   # app | erp_import
    raw_date = mapped_column(TEXT)
    ref = mapped_column(TEXT)                                 # extra: ERP document number


class Slitting(Demo, Timestamps, Base):
    __tablename__ = "slitting"
    id = mapped_column(ID, primary_key=True)                  # SLT-####
    date = mapped_column(DATE, nullable=False)
    jumbo_roll_id = mapped_column(ID, ForeignKey("rolls.id"), nullable=False)
    jumbo_width_mm = mapped_column(INT, nullable=False)
    length_m = mapped_column(QTY, nullable=False)
    outputs = mapped_column(JSONT)
    operator = mapped_column(TEXT)


class PartyLaminate(Demo, Timestamps, Base):
    __tablename__ = "party_laminate"
    id = mapped_column(ID, primary_key=True)                  # PLM-####
    date = mapped_column(DATE, nullable=False)
    client_id = mapped_column(ID, ForeignKey("clients.id"), nullable=False)
    movement = mapped_column(TEXT, nullable=False)            # in | out
    laminate = mapped_column(TEXT)
    width_mm = mapped_column(INT)
    qty_m = mapped_column(QTY, nullable=False)
    job_card = mapped_column(ID, ForeignKey("jobs.job_card"))


# ------------------------------------------------------------------ production


class PressSetup(Demo, Timestamps, Base):
    __tablename__ = "press_setup"
    job_card = mapped_column(ID, ForeignKey("jobs.job_card"), primary_key=True)
    machine_id = mapped_column(ID, ForeignKey("machines.id"), primary_key=True)
    web_width_mm = mapped_column(INT)
    die_id = mapped_column(ID, ForeignKey("dies.id"))
    units = mapped_column(JSONT)
    speed_target_mpm = mapped_column(INT)
    est_ink_kg = mapped_column(QTY)
    notes = mapped_column(LONG)
    updated_by = mapped_column(TEXT)


class Run(Demo, Timestamps, Base):
    __tablename__ = "runs"
    id = mapped_column(ID, primary_key=True)                  # RUN-#####
    job_card = mapped_column(ID, ForeignKey("jobs.job_card"), nullable=False, index=True)
    machine_id = mapped_column(ID, ForeignKey("machines.id"), nullable=False, index=True)
    shift = mapped_column(TEXT)
    operator = mapped_column(TEXT)
    start = mapped_column(TS, nullable=False)
    end = mapped_column(TS)
    hours = mapped_column(QTY)
    printed_qty = mapped_column(INT, nullable=False, default=0)
    used_m = mapped_column(QTY)
    stops = mapped_column(JSONT)


class QC(Demo, Timestamps, Base):
    __tablename__ = "qc"
    id = mapped_column(ID, primary_key=True)                  # QC-#####
    date = mapped_column(DATE, nullable=False)
    job_card = mapped_column(ID, ForeignKey("jobs.job_card"), nullable=False, index=True)
    run_id = mapped_column(ID, ForeignKey("runs.id"))
    checked = mapped_column(INT, nullable=False)
    approved = mapped_column(INT, nullable=False)
    rejected = mapped_column(INT, nullable=False)
    decision = mapped_column(TEXT, nullable=False)
    defects = mapped_column(JSONT)
    inspector = mapped_column(TEXT)
    notes = mapped_column(LONG)


__all__ = ["Enquiry", "Quote", "Job", "Die", "Design", "Plate", "Grn", "Roll", "Issue", "Slitting",
           "PartyLaminate", "PressSetup", "Run", "QC"]
