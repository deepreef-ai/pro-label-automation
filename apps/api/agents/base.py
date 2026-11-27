"""Shared agent interface (SPEC 4). Every agent module registers one :class:`Agent`.

An agent only *reads* the database and returns :class:`Draft` findings. It never writes:
the runner (``agents.runner``) stores findings (deduped by ``dedupe_key``), and a human
Approve executes ``suggested_action`` through ``agents.actions``.

Numbers in a finding always come from ``core.rules`` / the app services. An LLM may only
reword ``title``/``detail`` (via ``ctx.word``), and every agent must work with no LLM.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

from sqlalchemy.orm import Session

AGENT_NAMES = (
    "import_checker", "store_watchdog", "wastage_watchdog", "planning",
    "collections", "payables", "month_end", "owner_brief",
)
ACTION_TYPES = (
    "draft_messages", "draft_purchase_request", "schedule_payment", "apply_fixes",
    "create_task", "draft_journal", "notify", "none",
)
Severity = Literal["high", "medium", "low"]


@dataclass
class Draft:
    """One finding an agent wants to raise (stored by the runner as an ``agent_findings`` row)."""

    severity: Severity
    title: str
    detail: str
    evidence: list[dict] = field(default_factory=list)  # [{"label": str, "link": "/route?..."}]
    action_type: str = "none"  # one of ACTION_TYPES
    payload: dict = field(default_factory=dict)  # shape per contract/fixtures/agents_findings_*.json
    dedupe_key: str = ""  # same key + still open = refresh, not a new finding

    def __post_init__(self) -> None:
        if self.action_type not in ACTION_TYPES:
            raise ValueError(f"unknown action type {self.action_type!r}")


@dataclass
class AgentContext:
    """What an agent gets at run time."""

    db: Session
    today: date
    settings: dict
    # word(kind, facts, fallback) -> str: optional LLM rewording through core.llm.get_gateway();
    # returns ``fallback`` when the LLM is off/unavailable. Never pass it numbers to compute.
    word: Callable[[str, dict, str], str]
    model_used: list[str] = field(default_factory=list)  # runner records "rules" or provider


@dataclass(frozen=True)
class Agent:
    name: str  # one of AGENT_NAMES
    label: str
    description: str
    schedule: str  # e.g. "daily 07:00", "after each run"
    run: Callable[[AgentContext], list[Draft]]


REGISTRY: dict[str, Agent] = {}


def register(agent: Agent) -> Agent:
    if agent.name not in AGENT_NAMES:
        raise ValueError(f"unknown agent {agent.name!r}")
    REGISTRY[agent.name] = agent
    return agent


def link(path: str, label: str) -> dict[str, Any]:
    return {"label": label, "link": path}
