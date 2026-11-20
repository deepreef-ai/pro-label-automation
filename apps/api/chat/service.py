"""Chat entry point (SPEC 4b): ``answer(message, role=..., history=..., gateway=..., api=...)``.

Order of work:
1. Deterministic navigation router ("open JC-1301", "show debtors", "go to store",
   "store kholo", "debtors dikhao" ...) -> ``navigate`` action, no LLM.
2. LangGraph agent (``chat.graph``) over ``core.llm.get_gateway()`` with read/draft tools.
3. If the gateway raises ``LLMUnavailable`` (or the model gives no usable answer):
   deterministic intent templates over the same tools, so the demo never breaks.

Whatever the path, actions are sanitised: only ``navigate`` (known route) and ``draft``
(produced by a draft tool, never by model text) survive. Nothing is ever written.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from chat import tools as T
from chat.tools import TOOLS, ToolContext, inr, job_card_from, pct
from core.llm.gateway import LLMUnavailable

log = logging.getLogger(__name__)

__all__ = ["ChatReply", "ToolContext", "answer", "suggestions", "route_navigation", "is_hindi"]


@dataclass
class ChatReply:
    reply: str
    actions: list = field(default_factory=list)
    sources: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"reply": self.reply, "actions": self.actions, "sources": self.sources}


# ----------------------------------------------------------------- language

_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
_HINGLISH = set(
    "hai hain ho kya kyu kyun kyon kaise kaisa kaun kaunse kaunsa kitna kitne kitni kab kahan ko ka ki ke "
    "mein me se par pe aaj kal mahine mahina hafte hafta likho likhiye batao bataiye bata dikhao dikha "
    "dikhaiye kholo khol karo kariye chahiye nahi nahin wala wale abhi sab sabhi bhejo bhej paisa paise "
    "udhaar udhar bakaya hisaab munafa faayda fayda lock hoga honge jaayega jayega raha rahe".split()
)
_HINGLISH_STRONG = {"kya", "kyun", "kyon", "kaise", "kaun", "kaunse", "kitna", "likho", "batao", "dikhao",
                    "kholo", "mein", "hai", "hain", "aaj", "mahine", "karo", "chahiye", "nahi", "munafa"}


def is_hindi(text: str) -> bool:
    if _DEVANAGARI.search(text or ""):
        return True
    words = re.findall(r"[a-z]+", (text or "").lower())
    hits = [w for w in words if w in _HINGLISH]
    strong = [w for w in words if w in _HINGLISH_STRONG]
    return bool(strong) and len(hits) >= 2


# ----------------------------------------------------------------- navigation router

SCREENS: list[tuple[str, str, str]] = [  # (route, English label, keywords "|"-separated)
    ("/", "Owner Dashboard", "dashboard|owner dashboard|home|home page|overview|kpi|kpis"),
    ("/marketing", "Marketing", "marketing|enquiries|enquiry|quotes|quotation|quotations|leads"),
    ("/jobs", "Jobs", "jobs|job cards|job list|ppic|planning|orders"),
    ("/design", "Design", "design|artwork|plates|dies|prepress"),
    ("/store", "Store", "store|stock|inventory|grn|grns|godown|maal|material|rolls|data quality"),
    ("/production", "Production", "production|machines|machine|runs|oee|press|morning report"),
    ("/qc", "QC", "qc|quality|quality check|inspection"),
    ("/dispatch", "Dispatch", "dispatch|dispatches|challan|challans|delivery|deliveries"),
    ("/money", "Money", "money|debtors|debtor|receivables|outstanding|invoices|invoice|payments|collections"
     "|creditors|payables|cash plan|cashplan|cash|p&l|pnl|udhaar|udhar|bakaya|paisa|hisaab|accounts"),
    ("/agents", "Agents Center", "agents|agent|agents center|findings|ai agents"),
    ("/floor", "Floor Board", "floor|floor board|shop floor|board"),
    ("/settings", "Settings", "settings|setting|tolerances|configuration|config"),
]
_SCREEN_WORDS: list[tuple[str, str]] = sorted(
    ((kw, route) for route, _, kws in SCREENS for kw in kws.split("|")), key=lambda x: -len(x[0])
)
ROUTE_LABELS = {route: label for route, label, _ in SCREENS}
KNOWN_ROUTES = tuple(ROUTE_LABELS)

_OPEN = re.compile(r"\b(open|go\s*to|goto|navigate\s+to|take\s+me\s+to|jump\s+to|switch\s+to|"
                   r"kholo|khol\s*do|khol|kholiye|le\s+chalo|chalo|jao|par\s+jao|pe\s+jao)\b", re.I)
_SHOW = re.compile(r"\b(show|display|view|list|dikhao|dikha\s*do|dikhaiye|dikha)\b", re.I)
_QUESTION = re.compile(r"\?|\b(why|how|what|which|who|when|whose|kya|kyu|kyun|kyon|kaise|kaun|kaunse|"
                       r"kitna|kitne|kab)\b", re.I)
_FILLER = set("me the my all a an of page screen tab list please pls ka ki ke wala wali section "
              "for to us our open show display view go take jump switch navigate".split())
_IDS = [
    (re.compile(r"\bINV[-\s]?(\d{3,5})\b", re.I), lambda n: f"/money?tab=invoices&id=INV-{n}", "invoice INV-{}"),
    (re.compile(r"\bDC[-\s]?(\d{3,5})\b", re.I), lambda n: f"/dispatch?id=DC-{n}", "challan DC-{}"),
    (re.compile(r"\bCL[-\s]?(\d{3})\b", re.I), lambda n: f"/money?tab=debtors&client=CL-{n}", "client CL-{}"),
    (re.compile(r"\bENQ[-\s]?(\d{3,5})\b", re.I), lambda n: f"/marketing?id=ENQ-{n}", "enquiry ENQ-{}"),
]


def _entity_route(text: str) -> tuple[str, str] | None:
    jc = job_card_from(text)
    if jc:
        return f"/jobs/{jc}", f"job card {jc}"
    for rx, to, label in _IDS:
        m = rx.search(text)
        if m:
            return to(m.group(1)), label.format(m.group(1))
    return None


def _screen_route(text: str) -> tuple[str, str] | None:
    t = f" {text.lower()} "
    for kw, route in _SCREEN_WORDS:
        if re.search(rf"(?<![a-z0-9]){re.escape(kw)}(?![a-z0-9])", t):
            return route, ROUTE_LABELS[route]
    return None


def route_navigation(message: str) -> tuple[str, str] | None:
    """Return ``(route, label)`` for a pure navigation request, else ``None``."""
    text = (message or "").strip()
    low = text.lower()
    if not low:
        return None
    if _OPEN.search(low) and not re.search(r"\b(how|kaise)\b", low):
        return _entity_route(text) or _screen_route(low)
    rest = _SHOW.sub(" ", low) if _SHOW.search(low) else low
    words = [w for w in re.findall(r"[a-z0-9&-]+", rest) if w not in _FILLER]
    if _QUESTION.search(low) or not words:
        return None
    rest_text = " ".join(words)
    if len(words) <= 3:
        ent = _entity_route(rest_text)
        if ent and re.fullmatch(r"(jc|inv|dc|cl|enq)[-\s]?\d{3,5}", rest_text.strip()):
            return ent
        scr = _screen_route(rest_text)
        if scr and (_SHOW.search(low) or len(words) <= 2):
            covered = re.sub(r"\s+", " ", rest_text)
            for kw, route in _SCREEN_WORDS:
                if route == scr[0]:
                    covered = re.sub(rf"(?<![a-z0-9]){re.escape(kw)}(?![a-z0-9])", " ", covered)
            if not covered.strip():
                return scr
    return None


# ----------------------------------------------------------------- action safety

def _safe_navigate(action: Any) -> dict | None:
    if not isinstance(action, dict) or action.get("type") != "navigate":
        return None
    to = action.get("to")
    if not isinstance(to, str) or not to.startswith("/") or "//" in to or len(to) > 200:
        return None
    path = to.split("?")[0].split("#")[0]
    if path in KNOWN_ROUTES or re.fullmatch(r"/jobs/JC-\d{3,5}", path):
        return {"type": "navigate", "to": to}
    return None


def _clean_draft(d: dict, role: str) -> dict | None:
    if d.get("type") != "draft" or d.get("allowed") is False:
        return None
    tool_roles = {"release_lock": {"owner"}}.get(str(d.get("entity")))
    if tool_roles and role not in tool_roles:
        return None
    if not (isinstance(d.get("endpoint"), str) and d["endpoint"].startswith("/api/")):
        return None
    body = d.get("body") if isinstance(d.get("body"), dict) else {}
    out = {"type": "draft", "entity": str(d.get("entity") or "record"), "endpoint": d["endpoint"],
           "body": body, "payload": body, "summary": str(d.get("summary") or "Confirm this change")}
    if d.get("text"):
        out["text"] = d["text"]
    return out


def sanitize_actions(actions: list, role: str) -> list:
    out, seen = [], set()
    for a in actions or []:
        clean = _safe_navigate(a) if isinstance(a, dict) and a.get("type") == "navigate" else (
            _clean_draft(a, role) if isinstance(a, dict) else None)
        if clean:
            key = (clean["type"], clean.get("to") or clean.get("endpoint"))
            if key not in seen:
                seen.add(key)
                out.append(clean)
    return out


# ----------------------------------------------------------------- deterministic templates

def _run(name: str, args: dict, ctx: ToolContext) -> dict:
    try:
        out = TOOLS[name].run(args, ctx)
    except Exception as exc:
        log.warning("chat tool %s failed: %s", name, exc)
        return {"error": str(exc)}
    return out if isinstance(out, dict) else {}


def _client_hint(message: str, ctx: ToolContext) -> dict | None:
    """Find a client mentioned in the message (by id, full or partial name)."""
    rows = T._items(T._get(ctx, "/api/clients"))
    low = T._norm_name(message)
    best, score = None, 0
    for r in rows:
        name = T._norm_name(r.get("name"))
        if str(r.get("id", "")).lower() in message.lower() or (name and name in low):
            return r
        words = [w for w in name.split() if len(w) > 2]
        hit = sum(1 for w in words if re.search(rf"\b{re.escape(w)}\b", low))
        if hit > score:
            best, score = r, hit
    return best if score >= 1 else None


def _client_phrase(message: str) -> str | None:
    m = re.search(r"(?:for|to|of|from)\s+([A-Z][\w&.\- ]{2,40}?)(?:\s+(?:ko|ka|ki|ke|this|in|on|\?)|[?.!,]|$)",
                  message)
    if m:
        return m.group(1).strip()
    m = re.search(r"^([A-Z][\w&.\- ]{2,40}?)\s+(?:ko|ka|ki|ke)\b", message)
    return m.group(1).strip() if m else None


def _fmt_date(d: Any) -> str:
    try:
        return date.fromisoformat(str(d)[:10]).strftime("%d-%b")
    except ValueError:
        return str(d)


def _t_locks(message: str, ctx: ToolContext, hi: bool) -> ChatReply:
    res = _run("list_debtors", {}, ctx)
    rows = (res.get("data") or {}).get("clients") or []
    at_risk = sorted([r for r in rows if r.get("lock_status") == "at_risk"], key=lambda r: str(r.get("locks_on")))
    locked = [r for r in rows if r.get("lock_status") == "locked"]
    week = re.search(r"\b(week|hafte|hafta|7 days)\b", message.lower())
    if week:
        try:
            today = date.fromisoformat(str((res.get("data") or {}).get("as_of"))[:10])
        except ValueError:
            today = date.today()
        soon = [r for r in at_risk if r.get("locks_on") and (date.fromisoformat(str(r["locks_on"])[:10])
                                                              - today).days <= 7]
        at_risk = soon or at_risk
    if not at_risk and not locked:
        reply = "अभी कोई क्लाइंट लॉक होने वाला नहीं है।" if hi else "No client is at risk of a lock right now."
    else:
        lines = [f"- {r.get('client_name')}: {inr(r.get('outstanding'))}, locks on {_fmt_date(r.get('locks_on'))}"
                 + (f" (promise {inr(r['promise'].get('amount'))} on {_fmt_date(r['promise'].get('date'))})"
                    if isinstance(r.get("promise"), dict) and r["promise"].get("amount") else "")
                 for r in at_risk]
        head = (f"{len(at_risk)} क्लाइंट जल्द लॉक हो सकते हैं (देय तिथि + ग्रेस के बाद):" if hi
                else f"{len(at_risk)} client(s) will lock soon unless they pay (due date + grace days):")
        reply = head + "\n" + "\n".join(lines)
        if locked:
            names = ", ".join(str(r.get("client_name")) for r in locked)
            reply += (f"\nपहले से लॉक: {names}।" if hi else f"\nAlready locked: {names}.")
    return ChatReply(reply, [{"type": "navigate", "to": "/money?tab=debtors"}], res.get("sources", []))


def _t_flag(jc: str, ctx: ToolContext, hi: bool) -> ChatReply:
    res = _run("explain_flag", {"job_card": jc}, ctx)
    data = res.get("data") or {}
    job = data.get("job") or {}
    failed = [c for c in data.get("checks") or [] if isinstance(c, dict) and c.get("ok") is False]
    parts = []
    if failed:
        parts += [f"{c.get('label')}: {c.get('detail') or pct(c.get('value'))}" for c in failed]
    elif job.get("flags"):
        parts.append("flags: " + ", ".join(str(f).replace("_", " ") for f in job["flags"]))
    if job.get("required_m") is not None and job.get("issued_m") is not None:
        parts.append(f"required {job['required_m']:,} m, planned {job.get('planned_m', '?'):,} m, "
                     f"issued {job['issued_m']:,} m" if isinstance(job.get("planned_m"), (int, float))
                     else f"required {job['required_m']} m, issued {job['issued_m']} m")
    for f in data.get("findings") or []:
        parts.append(f"{f.get('agent')} finding {f.get('id')}: {f.get('title')}")
    if not parts:
        reply = (f"{jc} पर अभी कोई फ़्लैग नहीं मिला।" if hi else f"I could not find any flag on {jc} right now.")
    else:
        head = f"{jc} फ़्लैग क्यों है:" if hi else f"Why {jc} is flagged:"
        reply = head + "\n" + "\n".join(f"- {p}" for p in parts)
    return ChatReply(reply, [{"type": "navigate", "to": f"/jobs/{jc}"}], res.get("sources", []))


def _t_profit(message: str, ctx: ToolContext, hi: bool) -> ChatReply:
    from core.rules.errors import money

    jc = job_card_from(message)
    if jc:
        res = _run("get_job", {"job_card": jc}, ctx)
        cost = ((res.get("data") or {}).get("job_360") or {}).get("cost") or {}
        if cost.get("profit") is not None:
            reply = (f"{jc} का मुनाफ़ा {inr(cost['profit'])} है (मार्जिन {pct(cost.get('margin_pct'))}, "
                     f"रेवेन्यू {inr(cost.get('revenue'))})।" if hi else
                     f"{jc} profit is {inr(cost['profit'])} on revenue {inr(cost.get('revenue'))} "
                     f"(margin {pct(cost.get('margin_pct'))}).")
            return ChatReply(reply, [{"type": "navigate", "to": f"/jobs/{jc}"}], res.get("sources", []))
    client = _client_hint(message, ctx)
    if client:
        res = _run("get_client", {"client": client.get("id")}, ctx)
        detail = res.get("data") or {}
        month = date.today().strftime("%Y-%m")
        jobs = [j for j in detail.get("jobs") or [] if isinstance(j, dict)]
        this_month = [j for j in jobs if str(j.get("created_on", "")).startswith(month)] or jobs[:3]
        lines, total, sources = [], money(0), list(res.get("sources", []))
        for j in this_month[:5]:
            r = _run("get_job", {"job_card": j.get("job_card")}, ctx)
            cost = ((r.get("data") or {}).get("job_360") or {}).get("cost") or {}
            if cost.get("profit") is not None:
                total += money(cost["profit"])
                lines.append(f"- {j.get('job_card')} ({j.get('product')}): {inr(cost['profit'])}")
                sources += r.get("sources", [])
        if lines:
            head = (f"{client.get('name')} का इस महीने का मुनाफ़ा (जॉब के हिसाब से): {inr(total)}" if hi
                    else f"Profit from {client.get('name')} this month (by job): {inr(total)}")
            return ChatReply(head + "\n" + "\n".join(lines),
                             [{"type": "navigate", "to": f"/money?tab=debtors&client={client.get('id')}"}],
                             sources)
    res = _run("dashboard_summary", {"period": "month"}, ctx)
    d = res.get("data") or {}
    if d.get("gross_profit") is not None:
        reply = (f"इस महीने का कुल मुनाफ़ा {inr(d['gross_profit'])} है (मार्जिन {pct(d.get('margin_pct'))})।" if hi
                 else f"Gross profit this month is {inr(d['gross_profit'])} "
                      f"(margin {pct(d.get('margin_pct'))}, revenue {inr(d.get('revenue'))}).")
        return ChatReply(reply, [{"type": "navigate", "to": "/"}], res.get("sources", []))
    return ChatReply("मुनाफ़े का डेटा अभी उपलब्ध नहीं है।" if hi else "Profit data is not available yet.",
                     [{"type": "navigate", "to": "/money?tab=pnl"}], [])


def _t_howto(message: str, ctx: ToolContext, hi: bool) -> ChatReply:
    res = _run("rag_search", {"query": message}, ctx)
    hits = (res.get("data") or {}).get("hits") or []
    low = message.lower()
    tips = []
    if "lock" in low:
        tips.append("Only the owner can release a lock: Money > Debtors > pick the locked client > "
                    "Release lock, give a reason. It is logged with time and re-applies after the "
                    "valid-until date if still unpaid.")
    if hits:
        snippet = re.sub(r"\s+", " ", hits[0]["text"]).strip()[:350]
        tips.append(f"From {hits[0]['source']}: \"{snippet}...\"")
    if not tips:
        tips.append("I could not find that in the documents. Try the search bar or ask about a "
                    "job card, client or screen.")
    reply = ("दस्तावेज़ों के अनुसार:\n" if hi else "") + "\n".join(tips)
    actions = [{"type": "navigate", "to": "/money?tab=debtors"}] if "lock" in low else []
    return ChatReply(reply, actions, res.get("sources", []))


def _t_reminder(message: str, ctx: ToolContext, hi: bool) -> ChatReply:
    client = _client_hint(message, ctx)
    q = (client or {}).get("id") or _client_phrase(message) or ""
    lang = "hi" if hi or re.search(r"\bhindi\b", message, re.I) else "en"
    draft = _run("draft_reminder", {"client": q, "lang": lang}, ctx)
    text = draft.get("text") or ""
    reply = (f"रिमाइंडर का ड्राफ़्ट तैयार है। भेजने से पहले Confirm दबाएँ:\n\n{text}" if hi else
             f"Here is a draft reminder. Press Confirm to log it:\n\n{text}")
    return ChatReply(reply, [draft], [{"label": "Debtors", "link": "/money?tab=debtors"}])


_NUM_UNIT = re.compile(r"(\d+(?:\.\d+)?)\s*(rolls?|roll|m|mtr|metres?|meters?|kg)\b", re.I)


def _t_grn(message: str, ctx: ToolContext, hi: bool) -> ChatReply:
    args: dict = {}
    m = _NUM_UNIT.search(message)
    if m:
        if m.group(2).lower().startswith("roll"):
            args["rolls"] = m.group(1)
        else:
            args["qty"] = m.group(1)
        tail = message[m.end():]
        item = re.split(r"\b(received|recd|aaya|aaye|from|se|by|ka|ki)\b", tail, maxsplit=1, flags=re.I)[0]
        args["item"] = item.strip(" :,-.") or None
    v = re.search(r"\bfrom\s+(.+?)(?:[.,;]|$)", message, re.I) or re.search(r"(\S+(?:\s+\S+)?)\s+se\b", message)
    if v:
        args["vendor"] = v.group(1).strip()
    draft = _run("draft_grn", args, ctx)
    reply = (f"GRN का ड्राफ़्ट: {draft.get('summary')}। जाँचकर Confirm दबाएँ।" if hi else
             f"Draft GRN: {draft.get('summary')}. Check it and press Confirm to save.")
    return ChatReply(reply, [draft], [{"label": "Store GRNs", "link": "/store?tab=grns"}])


def _t_release(message: str, ctx: ToolContext, hi: bool) -> ChatReply:
    client = _client_hint(message, ctx)
    q = (client or {}).get("id") or _client_phrase(message) or ""
    draft = _run("draft_release_lock", {"client": q}, ctx)
    if draft.get("allowed") is False:
        reply = ("केवल मालिक (owner) ही क्लाइंट का लॉक हटा सकते हैं। कृपया owner से कहें।" if hi
                 else draft.get("refusal") or "Only the owner can release a client lock.")
        return ChatReply(reply, [{"type": "navigate", "to": "/money?tab=debtors"}], [])
    reply = (f"ड्राफ़्ट तैयार: {draft.get('summary')}। Confirm दबाने पर ही लॉक हटेगा।" if hi else
             f"Draft ready: {draft.get('summary')}. Nothing changes until you press Confirm.")
    return ChatReply(reply, [draft], [{"label": "Debtors", "link": "/money?tab=debtors"}])


def _t_simple(tool: str, args: dict, ctx: ToolContext, hi: bool, to: str) -> ChatReply:
    res = _run(tool, args, ctx)
    data = res.get("data") or {}
    lines: list[str] = []
    if tool == "alerts":
        lines = [f"- [{a.get('severity')}] {a.get('title')}" for a in (data.get("alerts") or [])[:6]]
    elif tool == "agent_findings":
        lines = [f"- [{f.get('severity')}] {f.get('title')} ({f.get('agent')})" for f in data.get("items") or []][:6]
    elif tool == "store_data_quality":
        lines = [f"- {c.get('label')}: {c.get('count')}" for c in (data.get("checks") or [])[:6]]
    elif tool == "dashboard_summary" and data.get("revenue") is not None:
        lines = [f"- Revenue: {inr(data.get('revenue'))}", f"- Gross profit: {inr(data.get('gross_profit'))}",
                 f"- Receivables: {inr(data.get('receivables'))} (overdue {inr(data.get('overdue'))})",
                 f"- Wastage: {pct(data.get('wastage_pct'))}, OEE: {pct(data.get('oee'))}"]
    elif tool == "get_job":
        job = data.get("job") or {}
        if job.get("job_card"):
            lines = [f"- {job.get('job_card')} {job.get('client_name')}: {job.get('product')}",
                     f"- Status: {job.get('status')}, order {job.get('order_qty')}, printed {job.get('printed_qty')}"]
    elif tool == "search":
        lines = [f"- {r.get('title')}: {r.get('subtitle')}" for r in (data.get("results") or [])[:6]]
    head = "यह रहा:" if hi else "Here is what I found:"
    if not lines:
        head = "अभी इसका डेटा नहीं मिला।" if hi else "I found no data for that yet."
    return ChatReply("\n".join([head] + lines), [{"type": "navigate", "to": to}], res.get("sources", []))


def deterministic_answer(message: str, ctx: ToolContext, hi: bool) -> ChatReply:
    """Template answers over tools, used when no LLM is available."""
    low = message.lower()
    jc = job_card_from(message)
    if re.search(r"\b(release|unlock|hatao|hata\s*do|khol\s*do)\b", low) and "lock" in low \
            and not re.search(r"\b(how|kaise)\b", low):
        return _t_release(message, ctx, hi)
    if re.search(r"\b(how|kaise|process|steps|policy|procedure|guide)\b", low):
        return _t_howto(message, ctx, hi)
    if re.search(r"\b(remind|reminder|yaad|follow[- ]?up message|whatsapp)\b", low):
        return _t_reminder(message, ctx, hi)
    if re.search(r"\b(record|grn|received|receive|aaya|aaye|inward)\b", low) and _NUM_UNIT.search(message):
        return _t_grn(message, ctx, hi)
    if jc and re.search(r"\b(why|flag|flagged|wastage|waste|kyun|kyon|kyu|high|problem|issue)\b", low):
        return _t_flag(jc, ctx, hi)
    if re.search(r"\b(profit|margin|munafa|fayda|faayda|kamai)\b", low):
        return _t_profit(message, ctx, hi)
    if re.search(r"\b(lock|locked|locks|at[- ]risk|debtors?|overdue|outstanding|udhaar|udhar|bakaya)\b", low):
        return _t_locks(message, ctx, hi)
    if re.search(r"\b(alert|alerts|attention|urgent|today|aaj)\b", low):
        return _t_simple("alerts", {}, ctx, hi, "/")
    if re.search(r"\b(finding|findings|agent|agents)\b", low):
        return _t_simple("agent_findings", {"status": "open"}, ctx, hi, "/agents")
    if re.search(r"\b(data quality|without job card|date fix|import)\b", low):
        return _t_simple("store_data_quality", {}, ctx, hi, "/store?tab=data-quality")
    if re.search(r"\b(revenue|sales|summary|kpi|cash|bikri)\b", low):
        return _t_simple("dashboard_summary", {"period": "month"}, ctx, hi, "/")
    if jc:
        return _t_simple("get_job", {"job_card": jc}, ctx, hi, f"/jobs/{jc}")
    reply = _t_simple("search", {"q": message[:80]}, ctx, hi, "/")
    if reply.reply.startswith(("I found no", "अभी")):
        reply.reply = ("AI मॉडल अभी उपलब्ध नहीं है। आप पूछ सकते हैं: 'JC-1301 खोलो', 'कौन से क्लाइंट लॉक होंगे?', "
                       "'Fresh Juice ko reminder likho'।" if hi else
                       "The AI model is offline right now, but I can still: open screens or job cards "
                       "('open JC-1301'), list clients about to lock, explain a flagged job, draft a "
                       "reminder or a GRN.")
        reply.actions = []
    return reply


# ----------------------------------------------------------------- main entry

def _nav_reply(route: str, label: str, hi: bool) -> ChatReply:
    text = f"{label} खोल रहा हूँ।" if hi else f"Opening {label}."
    return ChatReply(text, [{"type": "navigate", "to": route}], [])


def answer(message: str, *, role: str = "owner", history: list | None = None,
           gateway: Any = None, api: Any = None) -> ChatReply:
    message = (message or "").strip()
    role = role or "owner"
    hi = is_hindi(message)
    if not message:
        return ChatReply("Ask me anything about jobs, stock, money or the plant." if not hi else
                         "जॉब, स्टॉक या पैसे के बारे में कुछ भी पूछें।")

    nav = route_navigation(message)
    if nav:
        return _nav_reply(nav[0], nav[1], hi)

    if api is None:
        from chat.api_client import default_api

        api = default_api(role)
    ctx = ToolContext(role=role, api=api)

    if gateway is None:
        from core.llm import get_gateway

        gateway = get_gateway()

    reply: ChatReply | None = None
    try:
        from chat.graph import AgentGaveUp, run_agent

        try:
            prompt = message + ("\n(Answer in Hindi.)" if hi else "")
            state = run_agent(prompt, role=role, gateway=gateway, ctx=ctx, history=history)
            actions = list(state.get("llm_actions") or []) + list(state.get("drafts") or [])
            text = str(state.get("answer") or "")
            refusals = [d.get("refusal") for d in state.get("drafts") or [] if d.get("allowed") is False]
            if refusals:
                text = (text + "\n\n" + refusals[0]).strip()
            reply = ChatReply(text, actions, list(state.get("sources") or []))
        except (LLMUnavailable, AgentGaveUp) as exc:
            log.info("chat: LLM path unavailable (%s); using deterministic answer", exc)
    except Exception as exc:  # never break the demo
        log.warning("chat agent failed: %s", exc)

    if reply is None or not reply.reply:
        reply = deterministic_answer(message, ctx, hi)

    reply.actions = sanitize_actions(reply.actions, role)
    seen, sources = set(), []
    for s in reply.sources:
        if isinstance(s, dict) and s.get("label") and s["label"] not in seen:
            seen.add(s["label"])
            sources.append({"label": str(s["label"]), "link": s.get("link")})
    reply.sources = sources[:8]
    return reply


# ----------------------------------------------------------------- suggestions

_SUGGESTIONS: dict[str, list[tuple[str, str]]] = {
    "owner": [("Which clients get locked this week?", "en"), ("Why is JC-1240 flagged?", "en"),
              ("Profit from Fresh Juice this month?", "en"), ("How do I release a lock?", "en"),
              ("Fresh Juice ko Hindi mein reminder likho", "hi"), ("Is mahine ka profit kitna hai?", "hi")],
    "accounts": [("Which clients get locked this week?", "en"), ("Show debtors", "en"),
                 ("Fresh Juice ko Hindi mein reminder likho", "hi"), ("Aaj kaunse MSME bill due hain?", "hi")],
    "store": [("Record: 10 rolls PP Silver received from Vendor X", "en"), ("Show stock", "en"),
              ("How many issue lines have no job card?", "en"), ("Store kholo", "hi")],
    "ppic": [("Open JC-1301", "en"), ("Is there enough PP Silver for next week's jobs?", "en"),
             ("Why is JC-1240 flagged?", "en"), ("Jobs dikhao", "hi")],
    "production": [("Why is JC-1240 flagged?", "en"), ("Go to production", "en"),
                   ("Aaj ka OEE kya hai?", "hi")],
    "qc": [("Open JC-1301", "en"), ("Go to QC", "en"), ("JC-1240 mein problem kya hai?", "hi")],
    "dispatch": [("Which clients are locked?", "en"), ("Go to dispatch", "en"), ("Open JC-1301", "en")],
    "design": [("Open JC-1301", "en"), ("Go to design", "en"), ("Design kholo", "hi")],
    "marketing": [("Go to marketing", "en"), ("Which clients get locked this week?", "en"),
                  ("Profit from Fresh Juice this month?", "en")],
}


def suggestions(role: str = "owner") -> dict:
    role = role if role in _SUGGESTIONS else "owner"
    return {"role": role, "suggestions": [{"text": t, "lang": lang} for t, lang in _SUGGESTIONS[role]]}
