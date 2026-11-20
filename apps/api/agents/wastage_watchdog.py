"""Wastage watchdog: runs above wastage / over-production tolerance, unusual runs, job leakage.

Reads only. Run wastage and flags come from ``app.services.production.list_runs`` (core.rules
wastage / overprod maths); job totals from ``app.services.jobs``. On top of the fixed tolerance an
IsolationForest per press looks for runs that are unusual against that press's own history
(fixed ``random_state``; skipped when a press has fewer than ``MIN_RUNS_FOR_ML`` runs).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from statistics import mean, median

from sqlalchemy import select

from agents._util_rules import as_date, day, inr, num, pct, word
from agents.base import Agent, AgentContext, Draft, link, register
from app.deps import T
from app.services import jobs as job_svc
from app.services import production as prod_svc
from app.services import store as store_svc
from core.rules import production as P
from core.rules.errors import dec, ratio

LOOKBACK_DAYS = 7  # runs that ended within a week are checked ("after each run")
LEAKAGE_LOOKBACK_DAYS = 30
MIN_RUNS_FOR_ML = 8
RANDOM_STATE = 42
MIN_ANOMALY_RATIO = 1.25  # an outlier must also be 25% above the press's typical wastage


def _recent(run: dict, since) -> bool:
    return run["status"] == "ended" and as_date(run["start"]) >= since


def _job_context(ctx: AgentContext, cards: set[str]) -> tuple[dict, dict, dict]:
    """(job row by card, damaged plates by card, worn/damaged dies by card)."""
    jb, pl, di, ds = T("jobs"), T("plates"), T("dies"), T("design")
    jobs = {r.job_card: r for r in ctx.db.execute(select(jb.c.job_card, jb.c.product, jb.c.item_id)
                                                  .where(jb.c.job_card.in_(cards)))}
    plates: dict[str, list] = defaultdict(list)
    for r in ctx.db.execute(select(pl.c.id, pl.c.job_card, pl.c.colour, pl.c.status)
                            .where(pl.c.job_card.in_(cards), pl.c.status.in_(("damaged", "worn")))
                            .order_by(pl.c.id)):
        plates[r.job_card].append(r)
    die_of = {r.job_card: r.die_id for r in ctx.db.execute(select(ds.c.job_card, ds.c.die_id)
                                                           .where(ds.c.job_card.in_(cards)))}
    dies: dict[str, list] = defaultdict(list)
    for r in ctx.db.execute(select(di.c.id, di.c.status, di.c.last_job_card)
                            .where(di.c.status.in_(("damaged", "worn")))):
        for jc in cards:
            if r.last_job_card == jc or die_of.get(jc) == r.id:
                dies[jc].append(r)
    return jobs, plates, dies


def _wastage_runs(ctx: AgentContext, runs: list[dict], tol: dict) -> list[Draft]:
    since = ctx.today - timedelta(days=LOOKBACK_DAYS)
    flagged = [r for r in runs if r["wastage_flag"] and _recent(r, since)]
    if not flagged:
        return []
    jobs, plates, dies = _job_context(ctx, {r["job_card"] for r in flagged})
    product_of = {jc: j.product for jc, j in jobs.items()}
    jb = T("jobs")
    all_products = {r.job_card: r.product for r in ctx.db.execute(select(jb.c.job_card, jb.c.product))}
    items = store_svc.items_by_id(ctx.db, {j.item_id for j in jobs.values() if j.item_id})
    out = []
    for r in flagged:
        job = jobs.get(r["job_card"])
        item = items.get(job.item_id) if job is not None and job.item_id else None
        cost = store_svc.line_value(r["wastage_m"], item) if item is not None else None
        # comparison: other day-shift runs of the same label, else this press's other runs
        same = [o for o in runs if o["id"] != r["id"] and o["wastage_pct"] is not None
                and all_products.get(o["job_card"]) == product_of.get(r["job_card"]) and o["shift"] == "day"]
        basis = "Day-shift runs of the same label average"
        if not same:
            same = [o for o in runs if o["id"] != r["id"] and o["wastage_pct"] is not None
                    and o["machine_id"] == r["machine_id"]]
            basis = f"Other runs on {r['machine_name']} average"
        compare = f" {basis} {pct(mean(o['wastage_pct'] for o in same))}." if same else ""
        stops = [s for s in r["stops"] if s.get("minutes")]
        stop_txt = ""
        if stops:
            reasons = defaultdict(list)
            for s in stops:
                reasons[s.get("reason") or "Stop"].append(int(s["minutes"]))
            stop_txt = " Stops: " + "; ".join(f"{len(m)} x {k.lower()} ({' + '.join(map(str, m))} min)"
                                              for k, m in reasons.items()) + "."
        tooling = [f"{p.colour.lower() if p.colour else ''} plate {p.id} is {p.status}".strip() for p in plates[r["job_card"]]]
        tooling += [f"die {d.id} is marked {d.status}" for d in dies[r["job_card"]]]
        tool_txt = f" {'; '.join(tooling)}." if tooling else ""
        tool_txt = tool_txt[:2].upper() + tool_txt[2:]
        material = f" of {item.name}" if item is not None else ""
        fallback = (f"{r['id']} ({day(r['start'])} {r['shift']}, operator {r['operator'] or 'n/a'}) used "
                    f"{num(r['used_m'], 1)} m against {num(r['required_m'], 0)} m required: "
                    f"{num(r['wastage_m'], 1)} m wasted ({pct(r['wastage_pct'])}, limit {pct(tol['wastage_tol'], 0)})"
                    + (f", about {inr(cost)}{material}" if cost else "") + "."
                    + stop_txt + tool_txt + compare)
        fixes = [f"replace {p.colour.lower() + ' ' if p.colour else ''}plate {p.id}" for p in plates[r["job_card"]]]
        fixes += [f"check die {d.id}" for d in dies[r["job_card"]]]
        task = (" and ".join(fixes) + f" before next {r['job_card']} repeat") if fixes else \
            f"Review set-up and stops on {r['machine_name']} for {r['job_card']} ({r['id']})"
        evidence = [link(f"/jobs/{r['job_card']}", r["job_card"]), link(f"/production?run={r['id']}", r["id"])]
        evidence += [link("/design?tab=plates", f"Plate {p.id}") for p in plates[r["job_card"]]]
        out.append(Draft(
            severity="high",
            title=f"{r['job_card']} wastage {pct(r['wastage_pct'])} on {r['machine_name'].split()[0]} {r['shift']} shift",
            detail=word(ctx, "wastage_watchdog.run", {"run": r["id"], "wastage_pct": r["wastage_pct"],
                                                      "limit": tol["wastage_tol"]}, fallback),
            evidence=evidence,
            action_type="create_task",
            payload={"assign_to": "production", "title": task[0].upper() + task[1:],
                     "due": (ctx.today + timedelta(days=1)).isoformat()},
            dedupe_key=f"wastage_watchdog:{r['id']}",
        ))
    return out


def _overprod(ctx: AgentContext, runs: list[dict], jobs: dict[str, dict], tol: dict) -> list[Draft]:
    since = ctx.today - timedelta(days=LOOKBACK_DAYS)
    cards = sorted({r["job_card"] for r in runs if r["overprod_flag"] and _recent(r, since)})
    out = []
    for jc in cards:
        j = jobs.get(jc)
        if j is None:
            continue
        extra = j["printed_qty"] - j["order_qty"]
        out.append(Draft(
            severity="medium",
            title=f"{jc} printed {pct(ratio(extra, j['order_qty']))} over the order quantity",
            detail=word(ctx, "wastage_watchdog.overprod", {"job": jc, "printed": j["printed_qty"],
                                                           "order": j["order_qty"]},
                        f"Press runs printed {num(j['printed_qty'])} labels for an order of {num(j['order_qty'])} "
                        f"({num(extra)} extra, limit {pct(tol['overprod_tol'], 0)}). Extra labels use paper and ink "
                        f"that cannot be billed."),
            evidence=[link(f"/jobs/{jc}", jc), link(f"/production?job={jc}", "Runs")],
            action_type="create_task",
            payload={"assign_to": "production", "title": f"Set the counter stop at the order quantity for {jc}",
                     "due": (ctx.today + timedelta(days=1)).isoformat()},
            dedupe_key=f"wastage_watchdog:overprod:{jc}",
        ))
    return out


def _anomalies(ctx: AgentContext, runs: list[dict]) -> list[Draft]:
    """IsolationForest on each press's own wastage % history; only unusually *high* recent runs."""
    since = ctx.today - timedelta(days=LOOKBACK_DAYS)
    by_machine: dict[str, list[dict]] = defaultdict(list)
    for r in runs:
        if r["machine_type"] == P.PRESS and r["status"] == "ended" and r["wastage_pct"] is not None:
            by_machine[r["machine_id"]].append(r)
    candidates = {m: rs for m, rs in by_machine.items()
                  if len(rs) >= MIN_RUNS_FOR_ML and any(_recent(r, since) and not r["wastage_flag"] for r in rs)}
    if not candidates:
        return []
    try:
        import numpy as np
        from sklearn.ensemble import IsolationForest
    except ImportError:  # ML is optional; the tolerance check above still runs
        return []
    out = []
    for _mid, rs in sorted(candidates.items()):
        x = np.array([[r["wastage_pct"]] for r in rs])
        model = IsolationForest(n_estimators=200, contamination="auto", random_state=RANDOM_STATE).fit(x)
        labels = model.predict(x)
        typical = median(r["wastage_pct"] for r in rs)
        for r, lab in zip(rs, labels, strict=True):
            if lab != -1 or r["wastage_flag"] or not _recent(r, since) or r["wastage_pct"] < typical * MIN_ANOMALY_RATIO:
                continue
            out.append(Draft(
                severity="medium" if r["wastage_pct"] >= 2 * typical else "low",
                title=f"{r['job_card']} wastage {pct(r['wastage_pct'])} is unusual for {r['machine_name']}",
                detail=word(ctx, "wastage_watchdog.anomaly", {"run": r["id"], "wastage_pct": r["wastage_pct"],
                                                              "typical": typical},
                            f"{r['id']} ({day(r['start'])} {r['shift']}, operator {r['operator'] or 'n/a'}) is within "
                            f"tolerance but stands out against {len(rs)} runs on this press (typical "
                            f"{pct(typical)}). Worth a look before it becomes a habit."),
                evidence=[link(f"/production?run={r['id']}", r["id"]), link(f"/jobs/{r['job_card']}", r["job_card"])],
                action_type="notify", payload={"to": "production"},
                dedupe_key=f"wastage_watchdog:anomaly:{r['id']}",
            ))
    return out


def _leakage(ctx: AgentContext, runs: list[dict], jobs: dict[str, dict], tol: dict) -> list[Draft]:
    """Store -> press -> QC -> dispatch: issued m vs used m, approved vs dispatched, per job."""
    since = ctx.today - timedelta(days=LEAKAGE_LOOKBACK_DAYS)
    used: dict[str, float] = defaultdict(float)
    active: set[str] = set()
    for r in runs:
        if r["machine_type"] == P.PRESS and r["used_m"] is not None:
            used[r["job_card"]] += r["used_m"]
        if as_date(r["start"]) >= since:
            active.add(r["job_card"])
    out = []
    for jc in sorted(active):
        j = jobs.get(jc)
        if j is None:
            continue
        notes, sev = [], "low"
        issued, u = dec(j["issued_m"]), dec(round(used[jc], 2))
        printing_done = j["status"] not in ("planned", "design", "printing")
        if u > 0 and issued > 0 and u > issued and P.material_flag(issued, u, tol["material_tol"]):
            notes.append(f"press used {num(u, 1)} m but store issued only {num(issued, 1)} m "
                         f"({num(u - issued, 1)} m not booked out)")
            sev = "medium"
        elif u > 0 and issued == 0:
            notes.append(f"press used {num(u, 1)} m but no paper was issued against the job card")
            sev = "medium"
        elif printing_done and u > 0 and issued > u and P.material_flag(issued, u, tol["material_tol"]):
            notes.append(f"store issued {num(issued, 1)} m, press used {num(u, 1)} m: "
                         f"{num(issued - u, 1)} m not returned to store")
        if j["dispatched_qty"] > j["qc_approved"]:
            notes.append(f"dispatched {num(j['dispatched_qty'])} labels but QC approved only {num(j['qc_approved'])}")
            sev = "high"
        if not notes:
            continue
        out.append(Draft(
            severity=sev,
            title=f"{jc}: material does not add up from store to dispatch",
            detail=word(ctx, "wastage_watchdog.leakage", {"job": jc}, "; ".join(notes)[:1].upper() + "; ".join(notes)[1:]
                        + f". Order {num(j['order_qty'])}, printed {num(j['printed_qty'])}, QC approved "
                        f"{num(j['qc_approved'])}, dispatched {num(j['dispatched_qty'])}."),
            evidence=[link(f"/jobs/{jc}", jc), link(f"/store?tab=issues&jc={jc}", "Issues"),
                      link(f"/production?job={jc}", "Runs")],
            action_type="create_task",
            payload={"assign_to": "store" if sev != "high" else "production",
                     "title": f"Reconcile paper and labels for {jc}",
                     "due": (ctx.today + timedelta(days=2)).isoformat()},
            dedupe_key=f"wastage_watchdog:leakage:{jc}",
        ))
    return out


def run(ctx: AgentContext) -> list[Draft]:
    tol = job_svc.tolerances(ctx.db)
    runs = prod_svc.list_runs(ctx.db)
    jobs = {j["job_card"]: j for j in job_svc.list_jobs(ctx.db, with_flags=False, tol=tol)}
    return [*_wastage_runs(ctx, runs, tol), *_overprod(ctx, runs, jobs, tol), *_anomalies(ctx, runs),
            *_leakage(ctx, runs, jobs, tol)]


AGENT = register(Agent(
    name="wastage_watchdog",
    label="Wastage watchdog",
    description="Runs above wastage / over-production tolerance",
    schedule="after each run",
    run=run,
))
