"""Settings defaults (SPEC 2, last bullet)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Defaults:
    """Owner-editable tolerances and parameters with the SPEC default values."""

    wastage_tol: float = 0.15
    overprod_tol: float = 0.10
    material_tol: float = 0.03
    ink_tol: float = 0.20
    slit_tol: float = 0.05
    grn_rate_tol: float = 0.05
    grace_days: int = 15
    msme_days: int = 45
    gst_rate: float = 0.18
    planning_extra: float = 0.10
    admin_pct: float = 0.05
    credit_days: int = 30
    ai_mode: str = "cloud"


DEFAULTS = Defaults()
