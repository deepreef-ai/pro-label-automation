"""Import checker: ERP/Excel import quality (dates, job cards, duplicates, unknown items/units).

Reads only. The date and job-card numbers come from ``app.services.store.data_quality`` (the
same report as the Store "Data quality" tab, day-first parsing via ``core.rules.dates``).
"""
from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select

from agents._util_rules import join_names, num, word
from agents.base import Agent, AgentContext, Draft, link, register
from app.deps import T
from app.services import store as store_svc


def _batch(dq: dict) -> str:
    """'ERP-2026-08-10' for an Aug-Oct export, 'ERP-2026-11' for one month (fixture style)."""
    f, t = dq["period_from"], dq["period_to"]
    if f[:7] == t[:7]:
        return f"ERP-{f[:7]}"
    return f"ERP-{f[:4]}-{f[5:7]}-{t[5:7]}" if f[:4] == t[:4] else f"ERP-{f[:7]}-{t[:7]}"


def _imported(ctx: AgentContext, table: str) -> list:
    t = T(table)
    rows = ctx.db.execute(select(t).where(t.c.source == "erp_import").order_by(t.c.date, t.c.id)).all()
    return rows or ctx.db.execute(select(t).order_by(t.c.date, t.c.id)).all()


def _date_fixes(ctx: AgentContext, dq: dict, batch: str) -> list[Draft]:
    fixes = dq["date_fixes"]
    n = fixes["count"]
    if not n:
        return []
    ex = fixes["examples"][:4]
    shown = [f"{e['raw']} ({e['doc_no']}) " + (f"read by Excel as {e['excel_read_as']}" if e["excel_read_as"]
                                                else "not a date for Excel") + f", fixed to {e['fixed_to']}"
             for e in ex]
    return [Draft(
        severity="medium",
        title=f"{num(n)} ERP date{'s were' if n != 1 else ' was'} read month-first; fixed to day-first",
        detail=word(ctx, "import_checker.dates", {"count": n, "source": dq["source"]},
                    f"In the {dq['source']}, {num(n)} dd-mm-yy dates were misread by Excel. Re-parsed day-first. "
                    f"{len(ex)} example{'s' if len(ex) != 1 else ''}: {'; '.join(shown)}. No quantities changed."),
        evidence=[link("/store?tab=data-quality#dates", "Data quality: date fixes")],
        action_type="apply_fixes",
        payload={"kind": "date_day_first", "count": n, "batch": batch},
        dedupe_key=f"import_checker:date_day_first:{batch}",
    )]


def _job_cards(ctx: AgentContext, issues: list, job_cards: set[str], batch: str) -> list[Draft]:
    """Non-ink lines without a job card (or with one not in PPIC): try to match them by roll."""
    items = store_svc.items_by_id(ctx.db)
    gaps = [r for r in issues
            if (not r.job_card or r.job_card not in job_cards)
            and (items[r.item_id].group if r.item_id in items else None) not in store_svc.INK_GROUPS]
    if not gaps:
        return []
    # a roll issued to exactly one known job card elsewhere tells us the job of the gap line
    roll_jobs: dict[str, set[str]] = defaultdict(set)
    it = T("issues")
    for roll_id, jc in ctx.db.execute(select(it.c.roll_id, it.c.job_card)
                                      .where(it.c.roll_id.is_not(None), it.c.job_card.is_not(None))):
        if jc in job_cards:
            roll_jobs[roll_id].add(jc)
    matched = [r for r in gaps if r.roll_id and len(roll_jobs.get(r.roll_id, ())) == 1]
    left = len(gaps) - len(matched)
    unknown = sum(1 for r in gaps if r.job_card)
    what = (f"{len(gaps) - unknown} without a job card" if unknown == 0 else
            f"{len(gaps) - unknown} without a job card, {unknown} with a job card not in PPIC")
    if matched:
        return [Draft(
            severity="medium",
            title=f"{len(gaps)} issue line{'s' if len(gaps) != 1 else ''} point to job cards not in PPIC",
            detail=word(ctx, "import_checker.job_cards", {"lines": len(gaps), "matched": len(matched)},
                        f"{what} (ink and varnish excluded). Matched {len(matched)} by roll number; "
                        f"{left} left for store to check."),
            evidence=[link("/store?tab=data-quality", "Data quality")],
            action_type="apply_fixes",
            payload={"kind": "job_card_match", "count": len(matched), "batch": batch},
            dedupe_key=f"import_checker:job_card_match:{batch}",
        )]
    return [Draft(
        severity="high" if len(gaps) / max(len(issues), 1) > 0.05 else "medium",
        title=f"{len(gaps)} issue line{'s' if len(gaps) != 1 else ''} have no usable job card",
        detail=f"{what} (ink and varnish excluded); none could be matched by roll. "
               f"Lines: {join_names([r.id for r in gaps], 5)}.",
        evidence=[link("/store?tab=issues&jc=missing", "Issues without job card")],
        action_type="notify", payload={"to": "store"},
        dedupe_key=f"import_checker:job_card_gap:{batch}",
    )]


def _duplicates(ctx: AgentContext, issues: list, grns: list, batch: str) -> list[Draft]:
    seen: dict[tuple, list[str]] = defaultdict(list)
    for r in issues:
        seen[("issue", r.date, r.job_card, r.item_id, str(r.qty), r.roll_id, r.ref)].append(r.id)
    for r in grns:
        seen[("grn", r.vendor_id, r.bill_no or r.ref, r.item_id, str(r.qty), str(r.rate))].append(r.id)
    dups = [ids for ids in seen.values() if len(ids) > 1]
    if not dups:
        return []
    extra = sum(len(ids) - 1 for ids in dups)
    return [Draft(
        severity="medium",
        title=f"{extra} duplicate line{'s' if extra != 1 else ''} in the ERP import",
        detail=word(ctx, "import_checker.duplicates", {"duplicates": extra},
                    f"Same date, item, quantity and document found more than once: "
                    f"{join_names([' = '.join(ids) for ids in dups], 4)}. Keeping the first of each; "
                    f"the copies would double the stock movement."),
        evidence=[link("/store?tab=data-quality", "Data quality")],
        action_type="apply_fixes",
        payload={"kind": "duplicate_lines", "count": extra, "batch": batch},
        dedupe_key=f"import_checker:duplicates:{batch}",
    )]


def _unknown_items(ctx: AgentContext, issues: list, grns: list, batch: str) -> list[Draft]:
    items = store_svc.items_by_id(ctx.db)
    unknown = sorted({r.item_id for r in (*issues, *grns) if r.item_id not in items})
    no_rate = sorted(i.id for i in items.values() if not i.rate)
    no_uom = sorted(i.id for i in items.values() if not i.uom)
    bad_sqm = sorted(i.id for i in items.values() if (i.rate_unit or "") == "per_sqm" and not store_svc.is_sqm_item(i))
    parts = []
    if unknown:
        parts.append(f"{len(unknown)} item code{'s' if len(unknown) != 1 else ''} not in the item master "
                     f"({join_names(unknown, 4)})")
    if no_rate:
        parts.append(f"{len(no_rate)} item{'s' if len(no_rate) != 1 else ''} without a rate ({join_names(no_rate, 4)})")
    if no_uom:
        parts.append(f"{len(no_uom)} item{'s' if len(no_uom) != 1 else ''} without a unit ({join_names(no_uom, 4)})")
    if bad_sqm:
        parts.append(f"{len(bad_sqm)} per-sq-m item{'s' if len(bad_sqm) != 1 else ''} not in metres or without a "
                     f"width ({join_names(bad_sqm, 4)})")
    if not parts:
        return []
    count = len(unknown) + len(no_rate) + len(no_uom) + len(bad_sqm)
    return [Draft(
        severity="high" if unknown else "medium",
        title=f"{count} item master gap{'s' if count != 1 else ''} block stock valuation",
        detail="; ".join(parts) + ". Lines with these items are left out of stock value until the item master is "
                                  "fixed.",
        evidence=[link("/store?tab=items", "Item master"), link("/store?tab=data-quality", "Data quality")],
        action_type="notify", payload={"to": "store"},
        dedupe_key=f"import_checker:item_master:{batch}",
    )]


def run(ctx: AgentContext) -> list[Draft]:
    dq = store_svc.data_quality(ctx.db)
    batch = _batch(dq)
    issues, grns = _imported(ctx, "issues"), _imported(ctx, "grns")
    jb = T("jobs")
    job_cards = {jc for (jc,) in ctx.db.execute(select(jb.c.job_card))}
    return [*_date_fixes(ctx, dq, batch), *_job_cards(ctx, issues, job_cards, batch),
            *_duplicates(ctx, issues, grns, batch), *_unknown_items(ctx, issues, grns, batch)]


AGENT = register(Agent(
    name="import_checker",
    label="Import checker",
    description="Checks ERP/Excel imports: dates, job cards, duplicates",
    schedule="daily 06:30",
    run=run,
))
