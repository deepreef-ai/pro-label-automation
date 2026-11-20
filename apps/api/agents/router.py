"""Agents screen API (SPEC 3/4, contract/openapi.yaml tag Agents; issue #18 G1).

Registered in ``app/main.py`` with prefix ``/api``.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

import agents  # noqa: F401  (fills agents.base.REGISTRY)
from agents import actions, owner_brief, runner
from agents.base import AGENT_NAMES, REGISTRY
from agents.wording import make_word
from app.audit import audit
from app.deps import DB, Role, T, allow, bad_request, conflict, not_found
from app.serialize import now

router = APIRouter()

AGENT_ROLES = ("owner", "ppic", "store", "production", "accounts")
STATUSES = ("open", "done", "rejected")
RECENT_RUNS = 20


# ---------------------------------------------------------------- helpers

def _finding_row(db: Session, finding_id: str):
    fnd = T("agent_findings")
    row = db.execute(select(fnd).where(fnd.c.id == finding_id)).first()
    if row is None:
        raise not_found("finding", finding_id)
    return row


def _open_finding(db: Session, finding_id: str) -> dict:
    f = runner.finding_dict(_finding_row(db, finding_id))
    if f["status"] != "open":
        raise conflict(f"finding {finding_id} is already {f['status']}")
    return f


def _get_finding(db: Session, finding_id: str) -> dict:
    return runner.finding_dict(_finding_row(db, finding_id))


# ---------------------------------------------------------------- reads

@router.get("/agents", dependencies=[allow(*AGENT_ROLES)])
def get_agents(db: DB) -> dict:
    runs, fnd = T("agent_runs"), T("agent_findings")
    open_by_agent = dict(db.execute(select(fnd.c.agent, func.count()).where(fnd.c.status == "open")
                                    .group_by(fnd.c.agent)).all())
    out = []
    for name in AGENT_NAMES:
        last = db.execute(select(runs).where(runs.c.agent == name)
                          .order_by(runs.c.started_at.desc(), runs.c.id.desc())).first()
        a = REGISTRY.get(name)
        out.append({
            "name": name,
            "label": a.label if a else name.replace("_", " ").capitalize(),
            "description": a.description if a else "Not installed yet",
            "schedule": a.schedule if a else "manual",
            "enabled": a is not None,
            "last_run_at": runner.run_dict(last, [])["started_at"] if last else None,
            "last_status": (last.status if last.status in ("ok", "failed") else None) if last else None,
            "open_findings": int(open_by_agent.get(name, 0)),
        })
    recent = db.execute(select(runs).order_by(runs.c.started_at.desc(), runs.c.id.desc()).limit(RECENT_RUNS)).all()
    return {"agents": out, "recent_runs": runner.runs_with_findings(db, recent)}


@router.get("/agents/findings", dependencies=[allow(*AGENT_ROLES)])
def get_findings(db: DB, status: str = "open") -> dict:
    if status not in STATUSES:
        raise bad_request(f"status must be one of {', '.join(STATUSES)}")
    fnd = T("agent_findings")
    q = select(fnd).where(fnd.c.status == status)
    if status == "open":
        sev = case({"high": 0, "medium": 1, "low": 2}, value=fnd.c.severity, else_=3)
        q = q.order_by(sev, fnd.c.created_at.desc(), fnd.c.id.desc())
    else:
        q = q.order_by(fnd.c.decided_at.desc(), fnd.c.id.desc())
    return {"status": status, "items": [runner.finding_dict(r) for r in db.execute(q).all()]}


@router.get("/agents/brief", dependencies=[allow("owner", "accounts")])
def get_brief(db: DB) -> dict:
    brief = owner_brief.build_brief(db, make_word(db))
    fnd = T("agent_findings")
    fid = db.execute(select(fnd.c.id).where(fnd.c.agent == "owner_brief")
                     .order_by(fnd.c.created_at.desc(), fnd.c.id.desc())).scalar()
    if fid:
        brief["finding_id"] = fid
    return brief


@router.get("/outbox", dependencies=[allow("owner", "accounts")])
def get_outbox(db: DB) -> dict:
    ob = T("outbox")
    rows = db.execute(select(ob).order_by(ob.c.created_at.desc(), ob.c.id.desc())).all()
    return {"items": [actions.outbox_dict(r) for r in rows]}


# ---------------------------------------------------------------- run

class RunRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    agent: str


@router.post("/agents/run", dependencies=[allow(*AGENT_ROLES)])
def post_run(body: RunRequest, db: DB, role: Role) -> dict:
    try:
        targets = runner.resolve(body.agent)
    except ValueError as exc:
        raise bad_request(str(exc)) from None
    return {"runs": [runner.run_one(db, a, role) for a in targets]}


# ---------------------------------------------------------------- decisions

@router.post("/agents/findings/{finding_id}/approve", dependencies=[allow(*AGENT_ROLES)])
def post_approve(finding_id: str, db: DB, role: Role) -> dict:
    f = _open_finding(db, finding_id)
    try:
        outbox, effects = actions.execute(db, f, role)
    except actions.ActionError as exc:
        db.rollback()
        raise bad_request(str(exc)) from None
    at = now()
    fnd = T("agent_findings")
    db.execute(fnd.update().where(fnd.c.id == finding_id).values(
        status="done", decided_by=role, decided_at=at, reason=None, updated_at=at))
    audit(db, role=role, action="finding_approve", entity="finding", entity_id=finding_id,
          before={"status": "open"},
          after={"status": "done", "action": f["suggested_action"]["type"], "outbox": [o["id"] for o in outbox],
                 "effects": effects})
    db.commit()
    return {"finding": _get_finding(db, finding_id), "outbox": outbox, "effects": effects}


class RejectRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    reason: str


@router.post("/agents/findings/{finding_id}/reject", dependencies=[allow(*AGENT_ROLES)])
def post_reject(finding_id: str, body: RejectRequest, db: DB, role: Role) -> dict:
    reason = body.reason.strip()
    if not reason:
        raise bad_request("reason is required")
    _open_finding(db, finding_id)
    at = now()
    fnd = T("agent_findings")
    db.execute(fnd.update().where(fnd.c.id == finding_id).values(
        status="rejected", decided_by=role, decided_at=at, reason=reason, updated_at=at))
    audit(db, role=role, action="finding_reject", entity="finding", entity_id=finding_id,
          before={"status": "open"}, after={"status": "rejected"}, reason=reason)
    db.commit()
    return _get_finding(db, finding_id)


class EditRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    payload: dict[str, Any]


@router.post("/agents/findings/{finding_id}/edit", dependencies=[allow(*AGENT_ROLES)])
def post_edit(finding_id: str, body: EditRequest, db: DB, role: Role) -> dict:
    f = _open_finding(db, finding_id)
    before = f["suggested_action"]
    after = {"type": before["type"], "payload": body.payload}
    fnd = T("agent_findings")
    db.execute(fnd.update().where(fnd.c.id == finding_id).values(suggested_action=after, updated_at=now()))
    audit(db, role=role, action="finding_edit", entity="finding", entity_id=finding_id,
          before={"payload": before["payload"]}, after={"payload": body.payload})
    db.commit()
    return _get_finding(db, finding_id)
