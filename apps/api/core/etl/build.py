"""Build the demo database: drop/create all tables, load real data (if present), add demo data.

``build_database(db_url, raw_dir=None) -> dict`` is used by the locked integration tests.

* ``raw_dir`` with the client's files (``System/`` + ``Review/``), or a folder of extract CSVs
  (``clients.csv`` ...): real masters and movements are loaded with ``is_demo = false``, then the
  demo stories are added on top.
* ``raw_dir`` None / missing / without those files: a SYNTHETIC-ONLY database (invented clients,
  items, vendors, jobs plus every fixture story). This is the CI path; it needs no client files.

v0.2 (SPEC 6): all of the above belongs to company ``CO-001`` (Pro Labels). Two made-up companies
(``CO-002``, ``CO-003``) are added from separate synthetic runs, plus the companies and users tables
(``core.etl.tenants``).
"""
from __future__ import annotations

import time
from pathlib import Path

from sqlalchemy import insert, text

from core.db import Base, get_engine
from core.etl.generate import Context, Rows, generate_demo
from core.etl.tenants import add_tenants

CHUNK = 500


def has_real_files(raw_dir: str | None) -> bool:
    """True when ``raw_dir`` holds the client workbooks or a folder of extract CSVs."""
    if not raw_dir:
        return False
    p = Path(raw_dir)
    if (p / "clients.csv").is_file() and (p / "issues.csv").is_file():
        return True
    from core.etl.extract import REVIEW_GLOB

    return any((p / "System").glob("06 *.xlsx")) and any((p / "System").glob("02 *.xlsx")) \
        and any(p.glob(REVIEW_GLOB))


def build_rows(raw_dir: str | None = None) -> tuple[Rows, str]:
    """Return CO-001's rows to insert and the mode (``real`` or ``synthetic``)."""
    R = Rows()
    ctx = Context()
    extra, overrides = None, None
    mode = "synthetic"
    if has_real_files(raw_dir):
        from core.etl.load import load_real

        extra, overrides = load_real(R, ctx, raw_dir)  # type: ignore[arg-type]
        mode = "real"
    generate_demo(R, ctx, settings_extra=extra, settings_overrides=overrides)
    return R, mode


def write_rows(engine, R: Rows) -> None:
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            rows = R.t.get(table.name)
            if not rows:
                continue
            # one statement per distinct key set keeps executemany fast and defaults intact
            groups: dict[tuple, list[dict]] = {}
            for r in rows:
                groups.setdefault(tuple(sorted(r)), []).append(r)
            for group in groups.values():
                for i in range(0, len(group), CHUNK):
                    conn.execute(insert(table), group[i:i + CHUNK])


def build_database(db_url: str, raw_dir: str | None = None) -> dict:
    """Drop and create every table, then fill it. Returns a summary with row counts per table."""
    t0 = time.time()
    from core import models  # noqa: F401  (register mappers)

    engine = get_engine(db_url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    R, mode = build_rows(raw_dir)
    others = add_tenants(R)  # stamps CO-001, adds companies/users, builds CO-002 and CO-003
    write_rows(engine, R)
    for rows in others:
        write_rows(engine, rows)
    counts = {}
    with engine.connect() as conn:
        for table in Base.metadata.sorted_tables:
            counts[table.name] = conn.execute(text(f'SELECT COUNT(*) FROM "{table.name}"')).scalar_one()
        demo = {}
        for table in Base.metadata.sorted_tables:
            if "is_demo" in table.c:
                demo[table.name] = conn.execute(
                    text(f'SELECT COUNT(*) FROM "{table.name}" WHERE is_demo = :t'), {"t": True}).scalar_one()
    engine.dispose()
    return {"db_url": db_url, "mode": mode, "tables": counts, "demo_rows": demo,
            "total_rows": sum(counts.values()), "seconds": round(time.time() - t0, 2)}
