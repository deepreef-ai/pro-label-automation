"""Executors for a finding's ``suggested_action`` (run only on a human Approve).

"AI drafts, humans approve": nothing here posts payments, changes money/stock tables or
sends anything off the laptop. Messages become simulated outbox rows; every other action
becomes a ``task`` outbox row addressed to the team that must act (a scheduled payment is
a task for Accounts). ``apply_fixes`` only records what was applied in the audit log (the
ETL already parsed the data day-first).

``execute(db, finding, role)`` returns ``(outbox_rows, effects)``. A payload that cannot be
executed raises :class:`ActionError` (the router answers 400 and commits nothing).
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import audit, next_id
from app.deps import T
from app.serialize import now, row_dict
from app.services.job360 import day_label, num, rs

TEAMS = {
    "owner": "Owner", "ppic": "PPIC", "design": "Design", "store": "Store", "production": "Production",
    "qc": "QC", "dispatch": "Dispatch", "accounts": "Accounts", "marketing": "Marketing",
}
CHANNEL_LABEL = {"whatsapp": "WhatsApp", "email": "email", "task": "task"}


class ActionError(ValueError):
    """The (possibly edited) payload cannot be executed."""


def outbox_dict(row: Any) -> dict:
    d = row_dict(row)
    return {
        "id": d["id"], "created_at": d.get("created_at"), "agent": d.get("agent") or "",
        "finding_id": d.get("finding_id"), "channel": d.get("channel") or "task", "to": d.get("to") or "",
        "subject": d.get("subject") or "", "body": d.get("body") or "", "status": d.get("status") or "draft",
        "approved_by": d.get("approved_by"), "sent_at": d.get("sent_at"), "simulated": bool(d.get("simulated", True)),
    }


def _team(value: Any) -> str:
    key = str(value or "").strip().lower()
    return TEAMS.get(key, str(value).strip() or "Owner")


def _name(db: Session, table: str, ident: Any) -> str:
    if not ident:
        return ""
    tbl = T(table)
    got = db.execute(select(tbl.c.name).where(tbl.c.id == str(ident))).scalar_one_or_none()
    return f"{got} ({ident})" if got else str(ident)


def _date(v: Any) -> str:
    try:
        return day_label(str(v)[:10]) + "-" + str(v)[:4]
    except (TypeError, ValueError):
        return str(v)


def _num(v: Any, what: str) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        raise ActionError(f"payload.{what} must be a number") from None


class _Ctx:
    def __init__(self, db: Session, finding: dict, role: str):
        self.db, self.finding, self.role = db, finding, role
        self.at = now()
        self.outbox: list[dict] = []

    def add(self, channel: str, to: str, subject: str, body: str) -> dict:
        tbl = T("outbox")
        ob_id = next_id(self.db, "outbox", "OB", 4)
        values = {
            "id": ob_id, "agent": self.finding["agent"], "finding_id": self.finding["id"], "channel": channel,
            "to": to, "subject": subject, "body": body,
            # simulated send: nothing leaves the laptop, the row records the human approval
            "status": "sent", "approved_by": self.role, "sent_at": self.at, "simulated": True,
            "created_at": self.at, "updated_at": self.at,
        }
        self.db.execute(tbl.insert().values(values))
        audit(self.db, role=self.role, action="outbox_create", entity="outbox", entity_id=ob_id,
              after={k: v for k, v in values.items() if k not in ("created_at", "updated_at")})
        row = self.db.execute(select(tbl).where(tbl.c.id == ob_id)).one()
        item = outbox_dict(row)
        self.outbox.append(item)
        return item

    def task(self, team: Any, subject: str, body: str) -> dict:
        return self.add("task", _team(team), subject, body)


def _messages(c: _Ctx, p: dict) -> list[str]:
    msgs = p.get("messages")
    if not isinstance(msgs, list) or not msgs:
        raise ActionError("payload.messages must be a non-empty list")
    counts: dict[str, int] = {}
    for i, m in enumerate(msgs):
        if not isinstance(m, dict) or not str(m.get("to") or "").strip() or not str(m.get("body") or "").strip():
            raise ActionError(f"payload.messages[{i}] needs 'to' and 'body'")
        channel = str(m.get("channel") or "email").lower()
        if channel not in CHANNEL_LABEL:
            raise ActionError(f"payload.messages[{i}].channel must be whatsapp, email or task")
        to = str(m["to"]).strip()
        if m.get("contact") and str(m["contact"]) not in to:
            to = f"{to} ({m['contact']})"
        subject = str(m.get("subject") or ("Payment reminder" if c.finding["agent"] == "collections"
                                           else c.finding["title"]))[:255]
        c.add(channel, to, subject, str(m["body"]).strip())
        counts[channel] = counts.get(channel, 0) + 1
    return [f"{n} {CHANNEL_LABEL[ch]} message{'s' if n != 1 else ''} marked sent (simulated; nothing left the laptop)"
            for ch, n in counts.items()]


def _purchase(c: _Ctx, p: dict) -> list[str]:
    if not p.get("item_id"):
        raise ActionError("payload.item_id is required")
    qty = _num(p.get("suggested_qty_m", p.get("qty_m")), "qty_m")
    if qty <= 0:
        raise ActionError("payload.qty_m must be above 0")
    item = _name(c.db, "items", p["item_id"])
    vendor = _name(c.db, "vendors", p.get("vendor_id")) or "the usual vendor"
    lines = [f"Please raise a purchase order for {num(qty, 2)} m of {item} from {vendor}."]
    if p.get("qty_m") is not None and _num(p["qty_m"], "qty_m") != qty:
        lines.append(f"Shortage is {num(_num(p['qty_m'], 'qty_m'), 2)} m; ordering a full roll.")
    if p.get("needed_by"):
        lines.append(f"Needed by {_date(p['needed_by'])}.")
    lines.append(f"Raised from agent finding {c.finding['id']}: {c.finding['title']}.")
    c.task("store", f"Purchase request: {item}, {num(qty, 2)} m", " ".join(lines))
    return [f"Purchase request for {num(qty, 2)} m of {item} sent to Store as a task (no PO created)"]


def _payment(c: _Ctx, p: dict) -> list[str]:
    if not p.get("vendor_id"):
        raise ActionError("payload.vendor_id is required")
    amount = _num(p.get("amount"), "amount")
    if amount <= 0:
        raise ActionError("payload.amount must be above 0")
    vendor = _name(c.db, "vendors", p["vendor_id"])
    when = _date(p["pay_on"]) if p.get("pay_on") else "the due date"
    mode = str(p.get("mode") or "neft").upper()
    body = (f"Please pay {vendor} {rs(amount)} on {when} by {mode}. Record the payment in Money > Creditors "
            f"once it is made (FIFO allocation is applied there). Approved from finding {c.finding['id']}.")
    c.task("accounts", f"Scheduled payment: {vendor} {rs(amount)} on {when}", body)
    return [f"Payment of {rs(amount)} to {vendor} scheduled as a task for Accounts (no payment posted)"]


def _task(c: _Ctx, p: dict) -> list[str]:
    title = str(p.get("title") or c.finding["title"]).strip()
    team = p.get("assign_to") or "owner"
    body = title + (f". Due {_date(p['due'])}." if p.get("due") else ".")
    if p.get("note"):
        body += f" {p['note']}"
    body += f" From agent finding {c.finding['id']}."
    c.task(team, title[:255], body)
    return [f"Task created for {_team(team)}: {title}"]


def _journal(c: _Ctx, p: dict) -> list[str]:
    entries = p.get("entries")
    if not isinstance(entries, list) or not entries:
        raise ActionError("payload.entries must be a non-empty list")
    lines = []
    for i, e in enumerate(entries):
        if not isinstance(e, dict) or not e.get("account"):
            raise ActionError(f"payload.entries[{i}] needs 'account' and 'amount'")
        lines.append(f"- {e['account']}: {rs(_num(e.get('amount'), f'entries[{i}].amount'))}"
                     + (f" ({e['note']})" if e.get("note") else ""))
    month = p.get("month") or ""
    body = (f"Draft journal for {month or 'the month'} (review and post in Tally):\n" + "\n".join(lines)
            + f"\nFrom agent finding {c.finding['id']}.")
    c.task("accounts", f"Draft journal {month}".strip(), body)
    return [f"Draft journal with {len(entries)} entr{'ies' if len(entries) != 1 else 'y'} sent to Accounts "
            f"(nothing posted)"]


def _notify(c: _Ctx, p: dict) -> list[str]:
    team = p.get("to") or p.get("assign_to") or "owner"
    body = str(p.get("message") or p.get("body") or f"{c.finding['title']}. {c.finding['detail']}").strip()
    c.task(team, str(p.get("subject") or c.finding["title"])[:255], body)
    return [f"{_team(team)} notified"]


def _fixes(c: _Ctx, p: dict) -> list[str]:
    audit(c.db, role=c.role, action="apply_fixes", entity="finding", entity_id=c.finding["id"],
          after=dict(p), reason=c.finding["title"])
    kind = str(p.get("kind") or "data fixes")
    count = p.get("count")
    what = f"{num(count)} {kind} fixes" if isinstance(count, (int, float)) else f"{kind} fixes"
    return [f"{what} recorded as applied in the audit log (the import already holds the corrected values)"]


def _none(_c: _Ctx, _p: dict) -> list[str]:
    return ["Marked done; no action needed"]


EXECUTORS: dict[str, Callable[[_Ctx, dict], list[str]]] = {
    "draft_messages": _messages,
    "draft_purchase_request": _purchase,
    "schedule_payment": _payment,
    "apply_fixes": _fixes,
    "create_task": _task,
    "draft_journal": _journal,
    "notify": _notify,
    "none": _none,
}


def execute(db: Session, finding: dict, role: str) -> tuple[list[dict], list[str]]:
    """Run ``finding['suggested_action']`` for ``role``. Writes outbox/audit rows; does not commit."""
    action = finding.get("suggested_action") or {}
    kind = action.get("type") or "none"
    payload = action.get("payload")
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise ActionError("payload must be an object")
    fn = EXECUTORS.get(kind)
    if fn is None:
        raise ActionError(f"unknown action type {kind!r}")
    c = _Ctx(db, finding, role)
    effects = fn(c, payload)
    return c.outbox, effects
