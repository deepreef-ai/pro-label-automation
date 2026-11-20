"""Runs agents and stores their findings (``agent_runs`` AR-####, ``agent_findings`` F-####).

- Agents run synchronously, one after another, each in its own transaction.
- Dedupe: a draft whose ``dedupe_key`` matches a still-open finding refreshes that finding
  (wording, severity, evidence and, unless a human edited it, the payload) instead of
  creating a new one. Done/rejected findings are never reopened.
- One agent crashing never stops the others: its run is stored as ``failed`` with a note.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from agents.base import ACTION_TYPES, AGENT_NAMES, REGISTRY, Agent, AgentContext, Draft
from agents.wording import make_word
from app.audit import audit, next_id
from app.deps import T, today
from app.routers.shell import load_settings
from app.serialize import jsonable, now, row_dict

log = logging.getLogger(__name__)


# ---------------------------------------------------------------- serializers

def finding_dict(row: Any) -> dict:
    d = row_dict(row)
    action = d.get("suggested_action") or {}
    if not isinstance(action, dict):
        action = {}
    kind = action.get("type") if action.get("type") in ACTION_TYPES else "none"
    payload = action.get("payload") if isinstance(action.get("payload"), dict) else {}
    return {
        "id": d["id"], "agent": d.get("agent") or "", "created_at": d.get("created_at"),
        "severity": d.get("severity") or "low", "title": d.get("title") or "", "detail": d.get("detail") or "",
        "evidence": [e for e in (d.get("evidence") or []) if isinstance(e, dict)],
        "suggested_action": {"type": kind, "payload": payload},
        "status": d.get("status") or "open", "decided_by": d.get("decided_by"),
        "decided_at": d.get("decided_at"), "reason": d.get("reason"),
    }


def run_dict(row: Any, finding_ids: list[str]) -> dict:
    d = row_dict(row)
    return {
        "id": d["id"], "agent": d.get("agent") or "", "started_at": d.get("started_at"),
        "finished_at": d.get("finished_at"), "status": d.get("status") or "ok",
        "findings_created": int(d.get("findings_created") or 0), "finding_ids": finding_ids,
        "model": d.get("model") or "rules", "note": d.get("note") or "",
    }


def runs_with_findings(db: Session, rows: list) -> list[dict]:
    fnd = T("agent_findings")
    ids = [r.id for r in rows]
    by_run: dict[str, list[str]] = {i: [] for i in ids}
    if ids:
        for fid, rid in db.execute(select(fnd.c.id, fnd.c.run_id).where(fnd.c.run_id.in_(ids)).order_by(fnd.c.id)):
            by_run[rid].append(fid)
    return [run_dict(r, by_run[r.id]) for r in rows]


# ---------------------------------------------------------------- running

def resolve(name: str) -> list[Agent]:
    """Agents for ``name`` ('all' or one agent name). Raises ValueError for an unknown/unavailable agent."""
    name = (name or "").strip()
    if name == "all":
        return [REGISTRY[n] for n in AGENT_NAMES if n in REGISTRY]
    if name not in AGENT_NAMES:
        raise ValueError(f"unknown agent {name!r}; use one of {', '.join(AGENT_NAMES)} or 'all'")
    if name not in REGISTRY:
        raise ValueError(f"agent {name} is not available")
    return [REGISTRY[name]]


def _dedupe_key(agent: str, draft: Draft) -> str:
    key = (draft.dedupe_key or "").strip() or f"title:{draft.title.strip().lower()}"
    return key if key.startswith(f"{agent}:") else f"{agent}:{key}"


def _was_edited(db: Session, finding_id: str) -> bool:
    log_ = T("audit_log")
    n = db.execute(select(func.count()).select_from(log_).where(and_(
        log_.c.entity == "finding", log_.c.entity_id == finding_id, log_.c.action == "finding_edit"))).scalar_one()
    return n > 0


def _store(db: Session, agent: str, run_id: str, drafts: list[Draft], role: str, at) -> tuple[list[str], int]:
    fnd = T("agent_findings")
    created: list[str] = []
    refreshed = 0
    for dr in drafts:
        if not isinstance(dr, Draft):
            raise TypeError(f"agent returned {type(dr).__name__}, expected Draft")
        key = _dedupe_key(agent, dr)
        values = {
            "severity": dr.severity if dr.severity in ("high", "medium", "low") else "medium",
            "title": dr.title[:255], "detail": dr.detail, "evidence": jsonable(list(dr.evidence or [])),
            "suggested_action": {"type": dr.action_type, "payload": jsonable(dict(dr.payload or {}))},
        }
        existing = db.execute(select(fnd).where(fnd.c.dedupe_key == key, fnd.c.status == "open")
                              .order_by(fnd.c.id.desc())).first()
        if existing is not None:
            if _was_edited(db, existing.id):  # keep the human-edited payload
                values.pop("suggested_action")
            db.execute(fnd.update().where(fnd.c.id == existing.id).values(**values, updated_at=at))
            refreshed += 1
            continue
        fid = next_id(db, "agent_findings", "F", 4)
        db.execute(fnd.insert().values(id=fid, run_id=run_id, agent=agent, status="open", dedupe_key=key,
                                       created_at=at, updated_at=at, **values))
        audit(db, role=role, action="finding_create", entity="finding", entity_id=fid,
              after={"agent": agent, "title": values["title"], "dedupe_key": key})
        created.append(fid)
    return created, refreshed


def _note(created: int, refreshed: int) -> str:
    if created and refreshed:
        return f"{created} new finding{'s' if created != 1 else ''}; {refreshed} open finding{'s' if refreshed != 1 else ''} refreshed"
    if created:
        return f"{created} new finding{'s' if created != 1 else ''}"
    if refreshed:
        return "No new findings; existing open findings refreshed"
    return "No findings"


def run_one(db: Session, agent: Agent, role: str = "owner") -> dict:
    """Run one agent and commit its run row + findings. Never raises for an agent error."""
    started = now()
    used: list[str] = []
    error: Exception | None = None
    drafts: list[Draft] = []
    try:
        ctx = AgentContext(db=db, today=today(), settings=load_settings(db), word=make_word(db, used),
                           model_used=used)
        drafts = list(agent.run(ctx) or [])
    except Exception as exc:  # one agent failing must not stop the others
        log.exception("agent %s failed", agent.name)
        error = exc
        db.rollback()
    model = "rules" + (" + " + ", ".join(dict.fromkeys(m for m in used if m and m != "rules")) if any(
        m and m != "rules" for m in used) else "")
    if error is None:
        try:
            return _record(db, agent.name, role, started, model, drafts, None)
        except Exception as exc:
            log.exception("agent %s: could not store findings", agent.name)
            db.rollback()
            error = exc
    return _record(db, agent.name, role, started, model, [], error)


def _record(db: Session, agent: str, role: str, started, model: str, drafts: list[Draft],
            error: Exception | None) -> dict:
    runs = T("agent_runs")
    run_id = next_id(db, "agent_runs", "AR", 4)
    db.execute(runs.insert().values(id=run_id, agent=agent, started_at=started, finished_at=started,
                                    status="running", findings_created=0, model=model, note="",
                                    created_at=started, updated_at=started))
    created, refreshed = ([], 0) if error is not None else _store(db, agent, run_id, drafts, role, started)
    if error is None:
        status, note = "ok", _note(len(created), refreshed)
    else:
        status, note = "failed", f"{type(error).__name__}: {error}"[:1000]
    finished = now()
    db.execute(runs.update().where(runs.c.id == run_id).values(
        finished_at=finished, status=status, findings_created=len(created), note=note, updated_at=finished))
    audit(db, role=role, action="agent_run", entity="agent_run", entity_id=run_id,
          after={"agent": agent, "status": status, "findings_created": len(created), "refreshed": refreshed,
                 "finding_ids": created, "note": note})
    db.commit()
    row = db.execute(select(runs).where(runs.c.id == run_id)).one()
    return run_dict(row, created)


def run_agents(db: Session, name: str, role: str = "owner") -> list[dict]:
    """``POST /api/agents/run``: run ``name`` ('all' or one agent). ValueError for an unknown agent."""
    return [run_one(db, a, role) for a in resolve(name)]
