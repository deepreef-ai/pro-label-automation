"""Build the demo database into PostgreSQL and turn on row-level security (issue #55 B3).

    PYTHONPATH=apps/api python infra/postgres/init_rls.py [--rebuild]

Runs as the database **owner / superuser** (``DATABASE_ADMIN_URL``), once, before the API starts:

1. builds the synthetic demo data (``core.etl.build_demo_db --synthetic``) when ``companies`` is
   missing or ``--rebuild`` is given (the build drops and recreates every table);
2. applies ``core.tenancy.rls_statements`` (ENABLE + FORCE RLS and a ``company_isolation`` policy
   on ``current_setting('app.company_id', true)`` for every company table);
3. creates the API's login role (``APP_DB_USER`` / ``APP_DB_PASSWORD``): not a superuser, not the
   table owner and ``NOBYPASSRLS``, so the policies always apply to it; grants it DML only;
4. self-check as that role: with no company set it sees **no** company rows, and scoped to one
   company it sees only that company's rows. Exit code 1 if RLS does not bite.

Superusers bypass RLS, which is why the API must connect as the app role, never as ``postgres``.
"""
from __future__ import annotations

import argparse
import os
import sys

from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url

ROLE_NAME_OK = set("abcdefghijklmnopqrstuvwxyz0123456789_")


def _ident(name: str) -> str:
    if not name or set(name) - ROLE_NAME_OK:
        raise SystemExit(f"invalid role name {name!r} (use a-z, 0-9, _)")
    return name


def _literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def role_statements(role: str, password: str, database: str) -> list[str]:
    """SQL that creates/updates the non-superuser API role and grants it data access only."""
    r = _ident(role)
    return [
        f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = {_literal(r)}) THEN "
        f"CREATE ROLE {r} LOGIN; END IF; END $$",
        f"ALTER ROLE {r} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS PASSWORD {_literal(password)}",
        f'GRANT CONNECT ON DATABASE "{database}" TO {r}',
        f"GRANT USAGE ON SCHEMA public TO {r}",
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {r}",
        f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {r}",
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {r}",
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {r}",
    ]


def app_url(admin_url: str, role: str, password: str) -> str:
    return make_url(admin_url).set(username=role, password=password).render_as_string(hide_password=False)


def self_check(url: str) -> list[str]:
    """Problems found when connecting as the app role (empty list = RLS bites)."""
    from core.db import get_engine
    from core.tenancy import scoped

    problems: list[str] = []
    eng = get_engine(url)
    try:
        with eng.connect() as conn:
            if conn.execute(text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user")).scalar():
                problems.append("app role is a superuser or has BYPASSRLS")
            companies = [r[0] for r in conn.execute(text("SELECT id FROM companies ORDER BY id"))]
            n = conn.execute(text("SELECT count(*) FROM jobs")).scalar()
            if n:
                problems.append(f"unscoped connection sees {n} jobs (expected 0)")
        for cid in companies:
            with scoped(eng, cid).connect() as conn:
                # raw SQL with no company filter: only RLS limits it
                seen = dict(conn.execute(text("SELECT company_id, count(*) FROM jobs GROUP BY company_id")).all())
                if set(seen) - {cid}:
                    problems.append(f"scoped to {cid} but sees jobs of {sorted(set(seen) - {cid})}")
                print(f"  {cid}: sees {seen.get(cid, 0)} jobs, other companies: {sorted(set(seen) - {cid}) or 'none'}")
    finally:
        eng.dispose()
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--rebuild", action="store_true", help="drop and rebuild the demo data even if present")
    args = ap.parse_args(argv)

    admin_url = os.environ.get("DATABASE_ADMIN_URL")
    if not admin_url or make_url(admin_url).get_backend_name() != "postgresql":
        raise SystemExit("set DATABASE_ADMIN_URL=postgresql+psycopg://<owner>:<pw>@<host>:5432/<db>")
    role = os.environ.get("APP_DB_USER", "label_app")
    password = os.environ.get("APP_DB_PASSWORD") or "label_app"

    from core.db import Base, get_engine
    from core.tenancy import rls_statements

    admin = get_engine(admin_url)
    if args.rebuild or not inspect(admin).has_table("companies"):
        print("building synthetic demo data into PostgreSQL ...")
        from core.etl import build_demo_db

        rc = build_demo_db.main(["--synthetic", "--db", admin_url])
        if rc:
            return rc
    else:
        print("demo data already present (use --rebuild to start over)")

    from core import models  # noqa: F401  (registers every table on Base.metadata)

    database = make_url(admin_url).database
    with admin.begin() as conn:
        stmts = rls_statements(Base.metadata)
        for sql in stmts:
            conn.exec_driver_sql(sql)
        print(f"row-level security on {len(stmts) // 4} company tables")
        for sql in role_statements(role, password, database):
            conn.exec_driver_sql(sql)
        print(f"app role {role!r}: login, no superuser, no BYPASSRLS, DML grants")
    admin.dispose()

    print("self-check as the app role:")
    problems = self_check(app_url(admin_url, role, password))
    for p in problems:
        print(f"  FAIL {p}")
    if problems:
        return 1
    print("RLS OK: no company set -> no rows; each company sees only its own rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
