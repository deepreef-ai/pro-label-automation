"""Collections agent: clients about to lock and broken promises -> drafted reminders (SPEC 4).

Reads only. Lock dates, outstanding and overdue amounts come from ``services.clients``
(``invoice_dicts`` + ``lock_state``, the same maths as the debtors page); promise status comes
from ``services.receivables.list_collections``. Each reminder is a fixed bilingual template
(English + Hindi in Devanagari) sent on WhatsApp and email; ``ctx.word`` may only reword the
English text, and a rewording that drops the amount or the date is thrown away.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select

from agents.base import Agent, AgentContext, Draft, link, register
from app.deps import T
from app.services import clients as cl_svc
from app.services import receivables as rc_svc

LOCK_WINDOW_DAYS = 10  # clients whose lock date falls within this many days
BROKEN_LOOKBACK_DAYS = 30  # broken promises older than this were already chased
HINDI_MONTHS = ("जनवरी", "फ़रवरी", "मार्च", "अप्रैल", "मई", "जून", "जुलाई", "अगस्त", "सितंबर",
                "अक्टूबर", "नवंबर", "दिसंबर")


# ---------------------------------------------------------------- formatting (shared by money agents)

def inr(value: float | Decimal) -> str:
    """Indian digit grouping: 1420012 -> 'Rs 14,20,012' (paise shown only when non-zero)."""
    d = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    sign = "-" if d < 0 else ""
    d = abs(d)
    whole, paise = divmod(d, 1)
    s = str(int(whole))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        s = ",".join(groups + [tail])
    if paise:
        s += f".{int(paise * 100):02d}"
    return f"{sign}Rs {s}"


def short_inr(value: float | Decimal) -> str:
    """Rounded lakh/crore form: 4260000 -> 'Rs 42.6 lakh', 21500000 -> 'Rs 2.15 crore'."""
    d = abs(Decimal(str(value)))
    sign = "-" if Decimal(str(value)) < 0 else ""
    if d >= Decimal("10000000"):
        return f"{sign}Rs {_trim(d / Decimal('10000000'), 2)} crore"
    if d >= Decimal("100000"):
        return f"{sign}Rs {_trim(d / Decimal('100000'), 1)} lakh"
    return inr(value)


def _trim(d: Decimal, places: int) -> str:
    s = f"{d.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)}"
    return s.rstrip("0").rstrip(".") if "." in s else s


def day_month(d: date) -> str:
    return f"{d.day}-{d.strftime('%b')}"


def _long_date(d: date) -> str:
    return f"{d.day} {d.strftime('%b')} {d.year}"


def _hindi_date(d: date) -> str:
    return f"{d.day} {HINDI_MONTHS[d.month - 1]} {d.year}"


# ---------------------------------------------------------------- data

def _clients(ctx: AgentContext) -> dict[str, dict]:
    cl = T("clients")
    rows = ctx.db.execute(select(cl.c.id, cl.c.name, cl.c.contact, cl.c.phone, cl.c.email, cl.c.credit_days,
                                 cl.c.lock_override_until)).all()
    return {r.id: dict(r._mapping) for r in rows}


def _locks(ctx: AgentContext, clients: dict[str, dict]) -> dict[str, dict]:
    """``services.clients.lock_state`` for every client, as of ``ctx.today``."""
    grace = int(ctx.settings.get("grace_days") or 15)
    by_client: dict[str, list[dict]] = defaultdict(list)
    for inv in cl_svc.invoice_dicts(ctx.db, None, as_of=ctx.today,
                                    credit_days={k: c["credit_days"] for k, c in clients.items()}):
        by_client[inv["client_id"]].append(inv)
    return {cid: cl_svc.lock_state(by_client[cid], client_id=cid, as_of=ctx.today, grace_days=grace,
                                   override_until=c["lock_override_until"]) for cid, c in clients.items()}


# ---------------------------------------------------------------- message templates

def _messages(ctx: AgentContext, client: dict, amount: float, *, lock_on: date | None,
              locked_since: date | None) -> list[dict]:
    contact = (client.get("contact") or "").strip()
    if not contact or contact.lower() == "accounts desk":
        contact_en, contact_hi = "Sir/Madam", "महोदय/महोदया"
    else:
        contact_en, contact_hi = contact, f"{contact} जी"
    amt = inr(amount)
    if locked_since is not None:
        en = (f"Dear {contact_en}, {amt} is overdue on the {client['name']} account, which is on hold since "
              f"{_long_date(locked_since)}. Kindly arrange payment so we can restart dispatches. - Accounts")
        hi = (f"प्रिय {contact_hi}, {client['name']} के खाते में {amt} बकाया है और खाता {_hindi_date(locked_since)} "
              f"से होल्ड पर है। कृपया भुगतान करें ताकि डिस्पैच फिर से शुरू हो सके। धन्यवाद - अकाउंट्स")
        key_date = _long_date(locked_since)
    else:
        assert lock_on is not None
        en = (f"Dear {contact_en}, {amt} is overdue on the {client['name']} account. To avoid a hold on "
              f"{_long_date(lock_on)}, kindly arrange payment before that date. Thank you. - Accounts")
        hi = (f"प्रिय {contact_hi}, {client['name']} के खाते में {amt} बकाया है। कृपया {_hindi_date(lock_on)} "
              f"से पहले भुगतान करें, ताकि खाता होल्ड पर न जाए। धन्यवाद - अकाउंट्स")
        key_date = _long_date(lock_on)
    facts = {"client": client["name"], "contact": contact_en, "amount": amt, "date": key_date}
    worded = ctx.word("collections_reminder", facts, en)
    if not worded or amt not in worded or key_date not in worded:
        worded = en  # the LLM may only reword: amount and date must survive verbatim
    body = f"{worded}\n\n{hi}"
    base = {"client_id": client["id"], "contact": contact, "subject": "Payment reminder / भुगतान अनुस्मारक",
            "amount": round(float(amount), 2)}
    return [
        {"channel": "whatsapp", "to": client["name"], "phone": client.get("phone") or "", "body": body, **base},
        {"channel": "email", "to": client["name"], "email": client.get("email") or "", "body": body, **base},
    ]


# ---------------------------------------------------------------- agent

def run(ctx: AgentContext) -> list[Draft]:
    clients = _clients(ctx)
    locks = _locks(ctx, clients)
    diary = rc_svc.list_collections(ctx.db)
    open_promise: dict[str, dict] = {}
    for c in sorted(diary, key=lambda c: (c["promise_date"] or "", c["id"])):
        if c["status"] == "open" and c["promise_date"] and c["client_id"] not in open_promise:
            open_promise[c["client_id"]] = c

    drafts: list[Draft] = []
    horizon = ctx.today + timedelta(days=LOCK_WINDOW_DAYS)

    # 1) clients that lock within the window
    locking = []
    for cid, lk in locks.items():
        if lk["lock_status"] == "at_risk" and lk["locks_on"] and date.fromisoformat(lk["locks_on"]) <= horizon:
            locking.append((date.fromisoformat(lk["locks_on"]), cid, lk))
    locking.sort(key=lambda t: (t[0], t[1]))
    if locking:
        total = sum((Decimal(str(lk["overdue_amount"])) for _, _, lk in locking), Decimal("0"))
        parts, late_promises, messages = [], [], []
        for lock_on, cid, lk in locking:
            client = clients[cid]
            parts.append(f"{client['name']} ({inr(lk['overdue_amount'])}, locks {day_month(lock_on)})")
            p = open_promise.get(cid)
            if p and date.fromisoformat(p["promise_date"]) >= lock_on:
                late_promises.append(f"{client['name']} promised payment on "
                                     f"{day_month(date.fromisoformat(p['promise_date']))}, which is after its "
                                     "lock date.")
            messages += _messages(ctx, client, lk["overdue_amount"], lock_on=lock_on, locked_since=None)
        n = len(locking)
        title = (f"{n} client{'s' if n != 1 else ''} lock{'' if n != 1 else 's'} within {LOCK_WINDOW_DAYS} days: "
                 f"{short_inr(total)} at risk")
        detail = ", ".join(parts) + "." + (" " + " ".join(late_promises) if late_promises else "")
        facts = {"clients": n, "at_risk": short_inr(total)}
        drafts.append(Draft(
            severity="high" if locking[0][0] <= ctx.today + timedelta(days=3) else "medium",
            title=_keep(ctx.word("finding_title", facts, title), title, [short_inr(total)]),
            detail=detail,
            evidence=[link("/money?tab=debtors&filter=at_risk", "Debtors (at risk)"),
                      link("/money?tab=collections", "Collections log")],
            action_type="draft_messages",
            payload={"messages": messages},
            dedupe_key=f"collections:lock_risk:{ctx.today.isoformat()}",  # = core.etl FINDING_KEYS
        ))

    # 2) broken promises (recent), one finding per diary entry
    since = ctx.today - timedelta(days=BROKEN_LOOKBACK_DAYS)
    for c in diary:
        if c["status"] != "broken" or not c["promise_date"]:
            continue
        pd = date.fromisoformat(c["promise_date"])
        lk = locks.get(c["client_id"])
        if pd < since or lk is None or lk["outstanding"] <= 0:
            continue
        client = clients[c["client_id"]]
        promised = inr(c["promise_amount"]) if c["promise_amount"] is not None else "payment"
        locked_since = date.fromisoformat(lk["locked_since"]) if lk["locked_since"] else None
        state = (f"client is locked since {day_month(locked_since)}" if locked_since
                 else f"client locks on {day_month(date.fromisoformat(lk['locks_on']))}" if lk["locks_on"]
                 else "client is not locked")
        lock_on = date.fromisoformat(lk["locks_on"]) if lk["locks_on"] else ctx.today + timedelta(days=1)
        drafts.append(Draft(
            severity="high" if locked_since or lock_on <= horizon else "medium",
            title=f"{client['name']} promise broken ({promised})",
            detail=(f"Promise for {day_month(pd)} ({c['id']}) not received; {state}. "
                    f"Outstanding {inr(lk['outstanding'])}."),
            evidence=[link(f"/money?tab=debtors&client={client['id']}", "Debtors"),
                      link("/money?tab=collections", "Collections log")],
            action_type="draft_messages",
            payload={"messages": _messages(ctx, client, lk["outstanding"], lock_on=lock_on,
                                           locked_since=locked_since)},
            dedupe_key=f"collections:promise_broken:{c['id']}",
        ))
    return drafts


def _keep(worded: str, fallback: str, must_have: list[str]) -> str:
    """Use the reworded text only if every number in ``must_have`` survived verbatim."""
    return worded if worded and all(m in worded for m in must_have) else fallback


AGENT = register(Agent(
    name="collections",
    label="Collections",
    description="Clients about to lock; drafts reminders",
    schedule="daily 07:00",
    run=run,
))
