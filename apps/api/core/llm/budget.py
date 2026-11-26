"""Per-company monthly AI budget and usage counter (SPEC 6.4, issue #52 F2; Udit: minimum cost).

Every AI call made for a company is logged in ``ai_usage`` (purpose, provider, tokens, rupee cost,
cache hit). Free providers and cache hits cost Rs 0; paid providers are priced from the token count
(``LLM_PRICE_IN_PER_M`` / ``LLM_PRICE_OUT_PER_M`` in USD per million tokens, default Claude's 4 / 20,
converted with ``USD_INR``, default 84).

``LLMGateway.complete(..., company_id=...)`` asks ``over()`` before calling any provider: at 100% of
``companies.ai_budget_month`` it raises ``LLMUnavailable`` and the caller uses its deterministic
fallback, so the demo never breaks. Crossing ``ai_alert_pct`` (80%) logs a warning; ``status()`` is
what ``/api/platform/usage`` and ``/api/company/profile`` show (B2 #54).
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime, timezone
from decimal import Decimal

log = logging.getLogger("core.llm.budget")

PAID_PRICE_IN, PAID_PRICE_OUT = 4.0, 20.0  # USD per million tokens (Claude, README)


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "") or default)
    except ValueError:
        return default


def current_month(today: date | None = None) -> str:
    """YYYY-MM of the demo day (``DEMO_TODAY``) or the real date."""
    if today is None:
        raw = os.environ.get("DEMO_TODAY", "").strip()
        today = date.fromisoformat(raw) if raw else date.today()
    return today.strftime("%Y-%m")


def estimate_tokens(text: str) -> int:
    return max(1, len(text or "") // 4)


def call_cost(paid: bool, tokens_in: int, tokens_out: int) -> float:
    """Rupee cost of one call (0 for free tiers)."""
    if not paid:
        return 0.0
    usd = (tokens_in * _env_float("LLM_PRICE_IN_PER_M", PAID_PRICE_IN)
           + tokens_out * _env_float("LLM_PRICE_OUT_PER_M", PAID_PRICE_OUT)) / 1_000_000
    return round(usd * _env_float("USD_INR", 84.0), 4)


class AiBudget:
    """Budget check and usage log backed by the app database (``companies`` + ``ai_usage``)."""

    def __init__(self, engine=None):
        self._engine = engine

    def _eng(self):
        if self._engine is not None:
            return self._engine
        from core.db import engine

        return engine()

    @staticmethod
    def _tables():
        from core.models import Base

        return Base.metadata.tables["companies"], Base.metadata.tables["ai_usage"]

    def status(self, company_id: str, month: str | None = None) -> dict:
        """``{month, budget, used, used_pct, alert_pct, alert, over, calls}`` for one company."""
        from sqlalchemy import func, select

        from core.tenancy import scoped

        companies, usage = self._tables()
        month = month or current_month()
        with self._eng().connect() as con:
            row = con.execute(select(companies.c.ai_budget_month, companies.c.ai_alert_pct)
                              .where(companies.c.id == company_id)).first()
        with scoped(self._eng(), company_id).connect() as con:
            used, calls = con.execute(
                select(func.coalesce(func.sum(usage.c.cost), 0), func.coalesce(func.sum(usage.c.calls), 0))
                .where(usage.c.month == month)).one()
        budget = float(row[0]) if row else 0.0
        alert_pct = float(row[1]) if row and row[1] is not None else 0.8
        used = float(Decimal(str(used)).quantize(Decimal("0.01")))
        pct = round(used / budget, 4) if budget > 0 else (1.0 if used > 0 else 0.0)
        return {"month": month, "budget": budget, "used": used, "used_pct": pct, "alert_pct": alert_pct,
                "alert": pct >= alert_pct, "over": row is not None and (budget <= 0 or used >= budget),
                "calls": int(calls)}

    def over(self, company_id: str) -> bool:
        try:
            return self.status(company_id)["over"]
        except Exception as exc:  # never break a request because the counter is unavailable
            log.warning("AI budget check failed for %s: %s", company_id, exc)
            return False

    def record(self, company_id: str, *, purpose: str, provider: str, model: str | None, tokens_in: int,
               tokens_out: int, cost: float, cached: bool) -> None:
        from sqlalchemy import insert

        from core.tenancy import scoped

        _, usage = self._tables()
        try:
            with scoped(self._eng(), company_id).begin() as con:
                con.execute(insert(usage).values(
                    company_id=company_id, at=datetime.now(timezone.utc), month=current_month(),
                    purpose=purpose, provider=provider, model=model, tokens_in=tokens_in, tokens_out=tokens_out,
                    cost=cost, cached=cached, calls=1))
            if cost:
                st = self.status(company_id)
                if st["alert"]:
                    log.warning("AI budget for %s at %.0f%% (Rs %.2f of Rs %.2f)%s", company_id,
                                st["used_pct"] * 100, st["used"], st["budget"],
                                "; AI answers now use fallback text" if st["over"] else "")
        except Exception as exc:
            log.warning("could not record AI usage for %s: %s", company_id, exc)
