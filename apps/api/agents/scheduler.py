"""Agent scheduler, one company at a time (SPEC 6.4, issue #55 B3).

    python -m agents.scheduler [--once] [--company CO-002|all]

For every company whose status is not ``paused`` it opens a session scoped to that company
(``core.tenancy.scoped``), so runs, findings, outbox rows and the audit log stay inside it:

* ``import_checker`` every 15 minutes (on the quarter hour),
* all agents daily at 08:00,
* the ``owner_brief`` digest daily at 09:00.

Times are plant time (IST). ``--once`` runs all agents for each company immediately and exits.
A simple sleep loop, no extra dependencies. One company failing never stops the others.
"""
from __future__ import annotations

import argparse
import logging
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.engine import Engine

IST = timezone(timedelta(hours=5, minutes=30), "IST")
ROLE = "owner"  # audit role of scheduled runs (the company owner's agents)
IMPORT_EVERY_MIN = 15
DAILY_ALL = (8, 0)
DAILY_BRIEF = (9, 0)

log = logging.getLogger("agents.scheduler")


def active_companies(engine: Engine, only: str = "all") -> list[str]:
    """Ids of companies that are not paused (``only`` = one id or 'all')."""
    from app.deps import T

    co = T("companies")
    stmt = select(co.c.id, co.c.status).order_by(co.c.id)
    if only and only != "all":
        stmt = stmt.where(co.c.id == only)
    with engine.connect() as conn:
        rows = conn.execute(stmt).all()
    if only and only != "all" and not rows:
        raise SystemExit(f"unknown company {only!r}")
    out = []
    for cid, status in rows:
        if (status or "").lower() == "paused":
            log.info("[%s] paused: skipped", cid)
            continue
        out.append(cid)
    return out


def run_for_company(engine: Engine, company_id: str, agent: str) -> list[dict]:
    """Run ``agent`` ('all' or one name) in a session scoped to ``company_id``. Never raises."""
    from agents import runner
    from core.db import SessionLocal
    from core.tenancy import scoped

    session = SessionLocal(bind=scoped(engine, company_id))
    try:
        runs = runner.run_agents(session, agent, role=ROLE)
    except Exception:
        log.exception("[%s] %s: run failed", company_id, agent)
        return []
    finally:
        session.close()
    for r in runs:
        log.info("[%s] %s %s: %s, %d new (%s)", company_id, r["id"], r["agent"], r["status"],
                 r["findings_created"], r["note"])
    return runs


def run_all_companies(engine: Engine, agent: str, only: str = "all") -> dict[str, list[dict]]:
    return {cid: run_for_company(engine, cid, agent) for cid in active_companies(engine, only)}


def due_jobs(now: datetime, last: dict[str, str]) -> list[str]:
    """Which jobs are due at ``now`` (IST). ``last`` maps job -> slot key already run (updated)."""
    jobs = []
    slot = now.replace(minute=now.minute - now.minute % IMPORT_EVERY_MIN, second=0, microsecond=0)
    checks = [("import_checker", slot.isoformat(), True)]
    for name, (h, m) in (("all", DAILY_ALL), ("owner_brief", DAILY_BRIEF)):
        checks.append((name, now.date().isoformat(), (now.hour, now.minute) >= (h, m)))
    for name, key, ready in checks:
        if ready and last.get(name) != key:
            last[name] = key
            jobs.append(name)
    # the 08:00 run already includes import_checker
    if "all" in jobs and "import_checker" in jobs:
        jobs.remove("import_checker")
    return jobs


def initial_marks(now: datetime) -> dict[str, str]:
    """Start-up state: daily jobs whose time has already passed today wait for tomorrow."""
    last: dict[str, str] = {}
    for name, (h, m) in (("all", DAILY_ALL), ("owner_brief", DAILY_BRIEF)):
        if (now.hour, now.minute) > (h, m):
            last[name] = now.date().isoformat()
    return last


def loop(engine: Engine, only: str = "all", clock: Callable[[], datetime] | None = None,
         sleep: Callable[[float], None] = time.sleep, max_ticks: int | None = None) -> None:
    clock = clock or (lambda: datetime.now(IST))
    last = initial_marks(clock())
    ticks = 0
    while max_ticks is None or ticks < max_ticks:
        ticks += 1
        for job in due_jobs(clock(), last):
            log.info("running %s for %s", job, only)
            run_all_companies(engine, job, only)
        now = clock()
        sleep(max(1.0, 60 - now.second))  # wake at the next minute


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m agents.scheduler", description=__doc__.split("\n\n")[0])
    parser.add_argument("--once", action="store_true", help="run all agents for each company now and exit")
    parser.add_argument("--company", default="all", help="CO-00x or 'all' (default)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    from core.db import engine

    eng = engine()
    if args.once:
        results = run_all_companies(eng, "all", args.company)
        failed = sum(1 for runs in results.values() for r in runs if r["status"] != "ok")
        log.info("done: %d companies, %d failed runs", len(results), failed)
        return 1 if failed else 0
    log.info("scheduler started for %s (import_checker every %d min, all agents %02d:%02d, brief %02d:%02d IST)",
             args.company, IMPORT_EVERY_MIN, *DAILY_ALL, *DAILY_BRIEF)
    try:
        loop(eng, args.company)
    except KeyboardInterrupt:
        log.info("scheduler stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
