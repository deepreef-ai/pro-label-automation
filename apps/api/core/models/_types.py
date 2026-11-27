"""Portable column types and mixins shared by every model (contract/schema.md)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Integer, Numeric, String, Text, false, func
from sqlalchemy.orm import Mapped, mapped_column

__all__ = ["ID", "TEXT", "LONG", "INT", "NUM", "QTY", "FRAC", "DATE", "TS", "BOOL", "JSONT",
           "Timestamps", "Demo"]

ID = String(32)          # business ids: JC-####, GRN-##### ...
TEXT = String(255)
LONG = Text()
INT = Integer()
NUM = Numeric(14, 2)     # rupees
QTY = Numeric(14, 3)     # metres, kg, sq m
FRAC = Numeric(7, 4)     # fractions 0..1
DATE = Date()
TS = DateTime(timezone=True)
BOOL = Boolean()
JSONT = JSON()


class Timestamps:
    """``created_at`` / ``updated_at`` on every table."""

    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(TS, server_default=func.now(), onupdate=func.now(),
                                                 nullable=False)


class Demo:
    """``is_demo`` on every table marked [demo]: generated rows true, client-file rows false."""

    is_demo: Mapped[bool] = mapped_column(BOOL, nullable=False, default=False, server_default=false(),
                                          index=True)
