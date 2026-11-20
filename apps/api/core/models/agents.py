"""Agents, outbox and feedback tables (contract/schema.md)."""
from __future__ import annotations

from sqlalchemy import ForeignKey
from sqlalchemy.orm import mapped_column

from ..db import Base
from ._types import BOOL, ID, INT, JSONT, LONG, TEXT, TS, Timestamps


class AgentRun(Timestamps, Base):
    __tablename__ = "agent_runs"
    id = mapped_column(ID, primary_key=True)                  # AR-####
    agent = mapped_column(TEXT, nullable=False, index=True)
    started_at = mapped_column(TS, nullable=False)
    finished_at = mapped_column(TS)
    status = mapped_column(TEXT, nullable=False, default="running")
    findings_created = mapped_column(INT, nullable=False, default=0)
    model = mapped_column(TEXT)
    note = mapped_column(LONG)


class AgentFinding(Timestamps, Base):
    __tablename__ = "agent_findings"
    id = mapped_column(ID, primary_key=True)                  # F-####
    run_id = mapped_column(ID, ForeignKey("agent_runs.id"), nullable=False, index=True)
    agent = mapped_column(TEXT, nullable=False, index=True)
    severity = mapped_column(TEXT, nullable=False)
    title = mapped_column(TEXT, nullable=False)
    detail = mapped_column(LONG)
    evidence = mapped_column(JSONT)
    suggested_action = mapped_column(JSONT)
    status = mapped_column(TEXT, nullable=False, default="open", index=True)
    decided_by = mapped_column(TEXT)
    decided_at = mapped_column(TS)
    reason = mapped_column(LONG)
    dedupe_key = mapped_column(TEXT, nullable=False, index=True)


class Outbox(Timestamps, Base):
    __tablename__ = "outbox"
    id = mapped_column(ID, primary_key=True)                  # OB-####
    agent = mapped_column(TEXT)
    finding_id = mapped_column(ID, ForeignKey("agent_findings.id"))
    channel = mapped_column(TEXT, nullable=False)
    to = mapped_column(TEXT)
    subject = mapped_column(TEXT)
    body = mapped_column(LONG)
    status = mapped_column(TEXT, nullable=False, default="draft")
    approved_by = mapped_column(TEXT)
    sent_at = mapped_column(TS)
    simulated = mapped_column(BOOL, nullable=False, default=True)


class Feedback(Timestamps, Base):
    __tablename__ = "feedback"
    id = mapped_column(ID, primary_key=True)                  # FB-####
    role = mapped_column(TEXT)
    screen = mapped_column(TEXT)
    message = mapped_column(LONG, nullable=False)
    rating = mapped_column(INT)
    status = mapped_column(TEXT, nullable=False, default="new")


__all__ = ["AgentRun", "AgentFinding", "Outbox", "Feedback"]
