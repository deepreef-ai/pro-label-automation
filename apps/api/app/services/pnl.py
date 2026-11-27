"""Monthly P&L: system figures vs the imported Tally P&L (``tally_pnl``), line by line.

System lines for month ``YYYY-MM`` (same heads as the job profit formula in
``core.rules.money.job_profit``):

- revenue   - taxable value of issued (non-draft) invoices dated in the month;
- material  - value of store issues in the month, except ink/varnish (``services.store.line_value``);
- plates    - cost of plates and dies made in the month;
- ink       - value of ink and varnish issued in the month (with or without a job card: the pool);
- salaries  - crew salary in ``machine_costs`` for the month;
- freight   - freight on the month's delivery challans;
- admin     - ``admin_share(revenue, admin_pct)``;
- overheads - other monthly machine cost in ``machine_costs`` (direct overhead);
- profit    - ``job_profit(...)`` of the lines above.
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.deps import T, today
from app.serialize import jsonable
from app.services.clients import invoice_dicts
from app.services.store import INK_GROUPS, items_by_id, line_value, month_bounds
from core.rules import money as M

LINES = (
    ("revenue", "Revenue (invoiced taxable)"),
    ("material", "Material"),
    ("plates", "Plates & dies"),
    ("ink", "Ink & varnish"),
    ("salaries", "Salaries (crew)"),
    ("freight", "Freight"),
    ("admin", "Admin share"),
    ("overheads", "Overheads"),
)
COSTS = tuple(k for k, _ in LINES if k != "revenue")


def default_month() -> str:
    """The last closed month before ``today()`` (the month-end review month)."""
    d = today()
    year, month = (d.year - 1, 12) if d.month == 1 else (d.year, d.month - 1)
    return f"{year:04d}-{month:02d}"


def _admin_pct(db: Session) -> Decimal:
    from app.routers.shell import load_settings  # local import: routers import services

    v = load_settings(db).get("admin_pct")
    return Decimal(str(v)) if v is not None else Decimal(str(M.DEFAULTS.admin_pct))


def system_lines(db: Session, month: str) -> dict[str, Decimal]:
    """System P&L heads for ``month`` (RuleError from ``month_bounds`` when malformed)."""
    first, last = month_bounds(month)
    zero = Decimal("0.00")
    revenue = sum((Decimal(str(i["taxable"])) for i in invoice_dicts(db)
                   if i["status"] != "draft" and first.isoformat() <= i["date"] <= last.isoformat()), zero)

    iss = T("issues")
    items = items_by_id(db)
    material = ink = zero
    for iid, qty in db.execute(select(iss.c.item_id, iss.c.qty).where(iss.c.date >= first, iss.c.date <= last)):
        item = items.get(iid)
        value = line_value(qty, item)
        if item is not None and (item.group or "") in INK_GROUPS:
            ink += value
        else:
            material += value

    pl, di, dc, mc = T("plates"), T("dies"), T("dispatches"), T("machine_costs")
    plates = M.money(
        db.execute(select(func.sum(pl.c.cost)).where(pl.c.made_on >= first, pl.c.made_on <= last)).scalar_one() or 0
    ) + M.money(
        db.execute(select(func.sum(di.c.cost)).where(di.c.made_on >= first, di.c.made_on <= last)).scalar_one() or 0
    )
    freight = M.money(db.execute(select(func.sum(dc.c.freight))
                                 .where(dc.c.date >= first, dc.c.date <= last)).scalar_one() or 0)
    crew, other = db.execute(select(func.sum(mc.c.crew_salary), func.sum(mc.c.other_cost))
                             .where(mc.c.month == month)).one()
    revenue = M.money(revenue)
    p = M.job_profit(revenue, material=material, plates=plates, ink=ink, salaries=crew or 0, freight=freight,
                     admin_share=M.admin_share(revenue, _admin_pct(db)), direct_overhead=other or 0)
    return {"revenue": p.revenue, "material": p.material, "plates": p.plates, "ink": p.ink,
            "salaries": p.salaries, "freight": p.freight, "admin": p.admin_share,
            "overheads": p.direct_overhead, "profit": p.profit}


def tally_lines(db: Session, month: str) -> tuple[dict[str, Decimal], dict[str, str], object]:
    """Tally amounts and notes by key for ``month`` plus the latest ``imported_at`` (None if not imported)."""
    tp = T("tally_pnl")
    amounts: dict[str, Decimal] = {}
    notes: dict[str, str] = {}
    imported = None
    for r in db.execute(select(tp).where(tp.c.month == month)).all():
        m = r._mapping
        amounts[m["key"]] = M.money(m["amount"] or 0)
        notes[m["key"]] = m["note"] or ""
        if m["imported_at"] is not None and (imported is None or m["imported_at"] > imported):
            imported = m["imported_at"]
    if amounts:
        t = M.job_profit(amounts.get("revenue", 0), *(amounts.get(k, 0) for k in COSTS))
        amounts["profit"] = t.profit
    return amounts, notes, imported


def _fmt(v: Decimal) -> str:
    return f"Rs {v:,.0f}" if v == v.to_integral_value() else f"Rs {v:,.2f}"


def pnl(db: Session, month: str) -> dict:
    """``GET /api/pnl``: contract ``Pnl`` (system vs Tally, diff = system - tally)."""
    system = system_lines(db, month)
    tally, notes, imported = tally_lines(db, month)
    have_tally = bool(tally)
    zero = Decimal("0.00")
    lines, gaps = [], 0
    for key, label in LINES:
        s, t = system[key], tally.get(key, zero)
        diff = s - t
        note = ""
        if have_tally and diff != 0:
            gaps += 1
            note = notes.get(key) or f"System {'higher' if diff > 0 else 'lower'} than Tally by {_fmt(abs(diff))}"
        lines.append({"key": key, "label": label, "system": float(s), "tally": float(t),
                      "diff": float(diff), "note": note})
    s_profit, t_profit = system["profit"], tally.get("profit", zero)
    difference = s_profit - t_profit
    if not have_tally:
        profit_note = f"No Tally P&L imported for {month}"
    elif difference == 0:
        profit_note = "" if gaps == 0 else "Line differences cancel out"
    elif gaps:
        profit_note = f"Gap explained by the {gaps} item{'s' if gaps != 1 else ''} above"
    else:
        profit_note = "Unexplained gap"
    lines.append({"key": "profit", "label": "Net profit", "system": float(s_profit), "tally": float(t_profit),
                  "diff": float(difference), "note": profit_note})
    return {
        "month": month, "lines": lines, "system_profit": float(s_profit), "tally_profit": float(t_profit),
        "difference": float(difference), "matched": have_tally and difference == 0 and gaps == 0,
        "tally_imported_at": jsonable(imported) if imported is not None else None,
    }
