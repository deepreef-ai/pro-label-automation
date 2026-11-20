"""``owner_brief`` agent and ``GET /api/agents/brief``: the owner's morning summary.

Every number comes from the app services (alerts, dashboard summary, client locks, which
use ``core.rules``); the text is a deterministic template. An LLM may only reword the
headline through ``word`` (it falls back to the template when off or unavailable).
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from agents.base import Agent, AgentContext, Draft, link, register
from app.deps import T, today
from app.serialize import now
from app.services import dashboard as dash
from app.services.job360 import day_label, rs

MAX_ITEMS = 6
_SEV = {"high": 0, "medium": 1, "low": 2}


def lakh(v: Any) -> str:
    """Display format only (Rs 42.6 lakh / Rs 86,400): the amount itself comes from the services."""
    v = float(v or 0)
    if abs(v) >= 100000:
        return f"Rs {v / 100000:.1f} lakh"
    return rs(v).replace(".00", "")


def _sentence(text: str) -> str:
    text = text.strip()
    return text if text.endswith((".", "!", "?")) else text + "."


def _items(db: Session) -> tuple[list[dict], dict]:
    alerts = dash.alerts(db, "owner")["alerts"]
    # one line per alert, high first; the lock list and big money items lead
    picked = sorted(alerts, key=lambda a: (_SEV.get(a["severity"], 3), a["area"] != "money"))[:MAX_ITEMS - 1]
    items = [{"text": _sentence(f"{a['title']}: {a['detail'].rstrip('.')}"), "severity": a["severity"],
              "link": a["link"]} for a in picked]

    fnd = T("agent_findings")
    open_n = db.execute(select(func.count()).select_from(fnd).where(
        fnd.c.status == "open", fnd.c.agent != "owner_brief")).scalar_one()
    if open_n:
        items.append({"text": f"{open_n} agent finding{'s' if open_n != 1 else ''} waiting for your approval.",
                      "severity": "medium", "link": "/agents"})

    s = dash.summary(db, "month")
    margin = f" ({s['margin_pct'] * 100:.0f}% margin)" if s.get("revenue") else ""
    oee = f", OEE {s['oee'] * 100:.0f}%" if s.get("oee") else ""
    items.append({"text": f"Month so far: revenue {lakh(s['revenue'])}, gross profit {lakh(s['gross_profit'])}"
                          f"{margin}{oee}, wastage {s['wastage_pct'] * 100:.1f}%.",
                  "severity": "low", "link": "/"})
    return items, s


def _headline(items: list[dict]) -> str:
    highs = [i["text"].split(": ")[0] for i in items if i["severity"] == "high"][:3]
    if not highs:
        return "No urgent issues this morning; the plant is on track."
    return "; ".join(highs) + "."


def build_brief(db: Session, word=None) -> dict:
    """``AgentBrief`` without ``finding_id`` (the router adds it). ``word`` is ``ctx.word`` or None."""
    items, _s = _items(db)
    template = _headline(items)
    headline = template
    if word is not None:
        headline = word("brief_headline", {"items": [i["text"] for i in items]}, template)
    return {
        "date": today().isoformat(),
        "generated_at": now().isoformat(),
        "headline": headline,
        "items": items,
        "source": "llm" if headline != template else "template",
    }


def run(ctx: AgentContext) -> list[Draft]:
    brief = build_brief(ctx.db, ctx.word)
    detail = brief["headline"]
    others = [i["text"] for i in brief["items"] if i["severity"] != "low"][:3]
    if others:
        detail += " " + " ".join(others)
    return [Draft(
        severity="low",
        title=f"Morning brief for {day_label(ctx.today.isoformat())} is ready",
        detail=detail,
        evidence=[link("/", "Owner dashboard")],
        action_type="none",
        payload={},
        dedupe_key=f"owner_brief:{ctx.today.isoformat()}",
    )]


AGENT = register(Agent(
    name="owner_brief",
    label="Owner brief",
    description="Morning summary for the owner",
    schedule="daily 07:15",
    run=run,
))
