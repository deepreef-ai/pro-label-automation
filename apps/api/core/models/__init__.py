"""ORM models for every table in contract/schema.md (plus ``fixed_assets`` and ``lists``).

v0.2 (SPEC 6): ``apply_tenancy`` adds ``company_id`` to every business table and makes keys per company.
"""
from ..db import Base
from ..tenancy import apply_tenancy
from .agents import AgentFinding, AgentRun, Feedback, Outbox
from .masters import (
                      AuditLog,
                      Client,
                      FixedAsset,
                      Item,
                      ListValue,
                      Machine,
                      MachineCost,
                      OpeningStock,
                      Settings,
                      StockHead,
                      Vendor,
)
from .money import Collection, Dispatch, Invoice, Payment, PaymentAllocation, Receipt, SupplierBill, TallyPnl
from .operations import (
                      QC,
                      Design,
                      Die,
                      Enquiry,
                      Grn,
                      Issue,
                      Job,
                      PartyLaminate,
                      Plate,
                      PressSetup,
                      Quote,
                      Roll,
                      Run,
                      Slitting,
)
from .tenancy import Company, User

apply_tenancy(Base.metadata)

__all__ = [
    "Base", "Client", "Vendor", "Item", "StockHead", "OpeningStock", "Machine", "MachineCost", "Settings",
    "AuditLog", "FixedAsset", "ListValue", "Enquiry", "Quote", "Job", "Design", "Plate", "Die", "Grn",
    "Issue", "Roll", "Slitting", "PartyLaminate", "PressSetup", "Run", "QC", "Dispatch", "Invoice",
    "Receipt", "Collection", "SupplierBill", "Payment", "PaymentAllocation", "TallyPnl", "AgentRun",
    "AgentFinding", "Outbox", "Feedback", "Company", "User",
]
