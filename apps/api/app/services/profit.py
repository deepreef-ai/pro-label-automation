"""Per-job costing and profit (SPEC 2: job profit), shared by Job 360, the dashboard and P&L.

Job profit = revenue - material - plates - ink - salaries - freight - admin_share - direct_overhead
(``core.rules.money.job_profit``). The lines are gathered here; all money maths is ``core.rules``:

- revenue: invoiced taxable (drafts count: the challan is billed), else PO value
  (``revenue_for_job``); ``revenue_basis`` is ``invoiced`` or ``po_value``.
- material: value of the job's store issues that are not ink/varnish (``services.store.line_value``,
  the same value an ``Issue`` shows).
- ink: ink/varnish issued to the job card + the job's share of the monthly ink pool
  (``services.store.ink_allocation``) for each month it ran on a press.
- plates: cost of the plates made for the job.
- salaries: crew cost of its ended **press** runs (hours x machine hour rate, as on the ``Run``).
- direct_overhead: crew cost of its ended offline runs (inspection, slitting, rewinding).
- freight: freight on its challans.
- admin_share: ``core.rules.money.admin_share(revenue, settings.admin_pct)``.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.deps import T
from app.routers.shell import load_settings
from app.services import production as prod
from app.services import store as st
from core.rules import money as M
from core.rules.errors import dec
from core.rules.settings import DEFAULTS

COST_LINES = ("material", "plates", "ink", "salaries", "freight", "admin_share", "direct_overhead")
ZERO = Decimal("0.00")


def admin_pct(db: Session) -> Decimal:
    v = load_settings(db).get("admin_pct")
    return dec(v if v is not None else DEFAULTS.admin_pct)


def _in(col, cards: set[str] | None):
    return col.in_(cards) if cards is not None else col.is_not(None)


def jobs_profit(db: Session, job_cards: Iterable[str] | None = None, *,
                runs: list[dict] | None = None) -> dict[str, dict]:
    """Contract ``JobCost`` per job card (all jobs when ``job_cards`` is None).

    ``runs`` may pass already-built contract ``Run`` dicts (``production.list_runs``) to save a query.
    """
    cards = {c for c in job_cards} if job_cards is not None else None
    jobs_t, inv_t, iss_t, pl_t, dc_t = T("jobs"), T("invoices"), T("issues"), T("plates"), T("dispatches")
    jstmt = select(jobs_t.c.job_card, jobs_t.c.order_qty, jobs_t.c.rate)
    if cards is not None:
        jstmt = jstmt.where(jobs_t.c.job_card.in_(cards))
    po = {jc: M.po_value(q or 0, r or 0) for jc, q, r in db.execute(jstmt)}
    if not po:
        return {}
    known = set(po)

    invoiced: dict[str, Decimal] = defaultdict(Decimal)
    for jc, qty, rate, gst in db.execute(select(inv_t.c.job_card, inv_t.c.qty, inv_t.c.rate, inv_t.c.gst_rate)
                                         .where(_in(inv_t.c.job_card, cards))):
        if jc in known:
            invoiced[jc] += M.invoice_amounts(qty or 0, rate or 0, gst if gst is not None else
                                              DEFAULTS.gst_rate).taxable

    items = st.items_by_id(db)
    material: dict[str, Decimal] = defaultdict(Decimal)
    ink: dict[str, Decimal] = defaultdict(Decimal)
    for jc, iid, qty in db.execute(select(iss_t.c.job_card, iss_t.c.item_id, iss_t.c.qty)
                                   .where(_in(iss_t.c.job_card, cards))):
        if jc not in known:
            continue
        it = items.get(iid)
        value = st.line_value(qty, it)
        if it is not None and (it.group or "") in st.INK_GROUPS:
            ink[jc] += value
        else:
            material[jc] += value

    plates: dict[str, Decimal] = defaultdict(Decimal)
    for jc, cost in db.execute(select(pl_t.c.job_card, pl_t.c.cost).where(_in(pl_t.c.job_card, cards))):
        if jc in known:
            plates[jc] += M.money(cost or 0)

    freight: dict[str, Decimal] = defaultdict(Decimal)
    for jc, f in db.execute(select(dc_t.c.job_card, dc_t.c.freight).where(_in(dc_t.c.job_card, cards))):
        if jc in known:
            freight[jc] += M.money(f or 0)

    if runs is None:
        runs = prod.list_runs(db) if cards is None or len(cards) > 1 else prod.list_runs(db, job_card=next(iter(cards)))
    salaries: dict[str, Decimal] = defaultdict(Decimal)
    overhead: dict[str, Decimal] = defaultdict(Decimal)
    press_months: dict[str, set[str]] = defaultdict(set)
    for r in runs:
        jc = r["job_card"]
        if jc not in known:
            continue
        if r["machine_type"] == "press":
            press_months[r["start"][:7]].add(jc)
        if r["crew_cost"] is None:
            continue
        (salaries if r["machine_type"] == "press" else overhead)[jc] += M.money(r["crew_cost"])
    for month in sorted(press_months):
        for row in st.ink_allocation(db, month)["rows"]:
            if row["job_card"] in press_months[month]:
                ink[row["job_card"]] += M.money(row["allocated_value"])

    pct = admin_pct(db)
    out: dict[str, dict] = {}
    for jc in sorted(known):
        revenue = M.revenue_for_job(invoiced.get(jc, ZERO), po[jc])
        basis = "invoiced" if M.money(invoiced.get(jc, ZERO)) > 0 else "po_value"
        p = M.job_profit(revenue, material=material.get(jc, ZERO), plates=plates.get(jc, ZERO),
                         ink=ink.get(jc, ZERO), salaries=salaries.get(jc, ZERO), freight=freight.get(jc, ZERO),
                         admin_share=M.admin_share(revenue, pct), direct_overhead=overhead.get(jc, ZERO))
        out[jc] = {
            "revenue": float(p.revenue),
            "revenue_basis": basis,
            **{k: float(getattr(p, k)) for k in COST_LINES},
            "profit": float(p.profit),
            "margin_pct": float(p.margin),
        }
    return out


def job_profit(db: Session, job_card: str) -> dict | None:
    """Contract ``JobCost`` for one job card, or None when the job does not exist."""
    return jobs_profit(db, [job_card]).get(job_card)


def cost_of(cost: dict[str, Any]) -> float:
    """Total cost of a ``JobCost`` dict (revenue - profit), for callers that need it."""
    return float(M.money(dec(cost["revenue"]) - dec(cost["profit"])))
