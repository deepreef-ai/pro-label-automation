"""Optional LLM rewording for agent text (``AgentContext.word``).

``make_word(db, used)`` returns ``word(kind, facts, fallback) -> str``. The deterministic
``fallback`` (written by the agent from rules-engine numbers) is always the answer unless
the LLM is switched on (settings ``ai_mode`` != ``"off"``), answers in time, and keeps
every number of the fallback. Any failure (``LLMUnavailable``, timeout, bad reply, a
dropped number) returns the fallback: the demo never breaks and never waits long.

Privacy: in cloud mode client, vendor and contact names are swapped for aliases before
the text leaves the machine (``core.llm.anonymizer``) and restored in the reply.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.deps import T
from app.routers.shell import load_settings
from app.serialize import jsonable

log = logging.getLogger(__name__)

Word = Callable[[str, dict, str], str]

# Seconds per wording call (agent text is short; the run must stay snappy).
TIMEOUT = float(os.environ.get("AGENT_LLM_TIMEOUT", "8"))
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
_MEMO: dict[tuple[str, str], tuple[str, str]] = {}  # (kind, fallback) -> (text, provider)
_MEMO_MAX = 500
# After a failure, skip the LLM for this many seconds (one slow/broken provider must not
# slow down every agent run or every brief).
BACKOFF_S = 120.0
_DOWN_UNTIL = [0.0]

SYSTEM = (
    "You reword short operations notes for the owner of a label-printing plant. "
    "Rewrite the text in plain, short business English. Keep every number, amount, date, "
    "name and id exactly as written; do not add facts, advice or numbers. "
    "Reply with the rewritten text only."
)


def _aliases(db: Session) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        cl, vn = T("clients"), T("vendors")
        for i, (name, contact) in enumerate(db.execute(select(cl.c.name, cl.c.contact).order_by(cl.c.id)), 1):
            if name:
                out.setdefault(name, f"Client-{i:03d}")
            if contact:
                out.setdefault(contact, f"Contact-{i:03d}")
        for i, (name,) in enumerate(db.execute(select(vn.c.name).order_by(vn.c.id)), 1):
            if name:
                out.setdefault(name, f"Vendor-{i:03d}")
    except Exception as exc:  # names are a privacy aid; never fatal
        log.warning("agent wording: could not load names to anonymise: %s", exc)
    return out


def _keeps_numbers(fallback: str, text: str) -> bool:
    have = set(_NUMBER.findall(text))
    return all(n in have for n in _NUMBER.findall(fallback))


def make_word(db: Session, used: list[str] | None = None) -> Word:
    """The ``ctx.word`` callable for one agent run. ``used`` collects the providers that answered."""
    try:
        mode = str(load_settings(db).get("ai_mode") or "cloud").lower()
    except Exception:
        mode = "off"
    state: dict = {"down": mode == "off", "anon": None}

    def word(kind: str, facts: dict, fallback: str) -> str:
        fallback = str(fallback or "")
        if state["down"] or not fallback.strip() or time.monotonic() < _DOWN_UNTIL[0]:
            return fallback
        hit = _MEMO.get((kind, fallback))
        if hit is not None:
            if used is not None and hit[1] not in used:
                used.append(hit[1])
            return hit[0]
        try:
            from core.llm import get_gateway
            from core.tenancy import company_of

            gateway = get_gateway()
            body = f"Kind: {kind}\nFacts: {json.dumps(jsonable(facts or {}), default=str)[:2000]}\nText: {fallback}"
            mapping: dict = {}
            if getattr(gateway, "mode", "cloud") == "cloud":
                if state["anon"] is None:
                    from core.llm.anonymizer import Anonymizer

                    state["anon"] = Anonymizer(_aliases(db))
                body, mapping = state["anon"].anonymize(body)
            result = gateway.complete(
                [{"role": "system", "content": SYSTEM}, {"role": "user", "content": body}],
                purpose="agent_wording", timeout=TIMEOUT, company_id=company_of(db),
            )
            text = (result.text or "").strip().strip('"').strip()
            if mapping:
                from core.llm.anonymizer import Anonymizer

                text = Anonymizer.restore(text, mapping)
            if not text or len(text) > max(400, 3 * len(fallback)) or not _keeps_numbers(fallback, text):
                return fallback
            provider = str(result.provider or "llm")
        except Exception as exc:  # LLMUnavailable, timeout, anything: stop trying for this run
            log.info("agent wording: LLM unavailable (%s); using deterministic text", exc)
            state["down"] = True
            _DOWN_UNTIL[0] = time.monotonic() + BACKOFF_S
            return fallback
        if len(_MEMO) >= _MEMO_MAX:
            _MEMO.clear()
        _MEMO[(kind, fallback)] = (text, provider)
        if used is not None and provider not in used:
            used.append(provider)
        return text

    return word
