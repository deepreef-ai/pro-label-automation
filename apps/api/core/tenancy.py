"""Multi-tenant isolation layer (SPEC 6.1, issue #51 F1).

Three pieces, all in ``core`` so every caller gets them for free:

1. ``apply_tenancy(metadata)`` (run once by ``core.models``): every business table gets
   ``company_id`` (FK ``companies``, NOT NULL, indexed). Business ids become unique **per company**:
   the primary key is ``(company_id, <old key>)`` and every foreign key between company tables
   becomes composite ``(company_id, col) -> (company_id, key)``, so a row can never point at another
   company's row. Tables with an autoincrement integer id keep it and just get ``company_id``.
2. A scoped connection: ``scoped(engine, company_id)`` returns the engine bound to one company.
   An engine hook adds ``company_id = :current`` to every SELECT (including joins and subqueries),
   UPDATE and DELETE on a company table, and INSERTs fill ``company_id`` from the same option.
   An unscoped engine (the ETL build) sees every company and must set ``company_id`` itself.
3. PostgreSQL row-level security: ``rls_statements(metadata)`` returns the policies for the
   product database (``app.company_id`` session setting); the Postgres option in ``infra/`` runs
   them (B3 #55). SQLite (the demo) relies on piece 2.

``core.rules`` stays pure maths with no notion of a company.
"""
from __future__ import annotations

import os

from sqlalchemy import (
    Column,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    PrimaryKeyConstraint,
    String,
    Table,
    UniqueConstraint,
    and_,
    event,
)
from sqlalchemy.engine import Engine
from sqlalchemy.sql import Delete, Select, Update, visitors
from sqlalchemy.sql.selectable import Alias, Join

COMPANY_OPTION = "company_id"
DEMO_COMPANY = "CO-001"
#: Platform tables: not owned by one company (``users.company_id`` is nullable, see SPEC 6.1).
PLATFORM_TABLES = frozenset({"companies", "users"})


def default_company() -> str:
    """Company used when a request carries no token in ``AUTH_MODE=demo`` (SPEC 6.2)."""
    return os.environ.get("DEMO_COMPANY_ID") or DEMO_COMPANY


def company_of(db) -> str | None:
    """The company a Session / Connection / Engine is scoped to (None = unscoped)."""
    try:
        bind = db.get_bind() if hasattr(db, "get_bind") else db
        return bind.get_execution_options().get(COMPANY_OPTION)
    except Exception:
        return None


def _company_from_context(context) -> str | None:
    return context.execution_options.get(COMPANY_OPTION)


def is_company_table(table: Table) -> bool:
    return table.name not in PLATFORM_TABLES and "company_id" in table.c


# ---- 1. schema ---------------------------------------------------------------------------------

def _autoinc_pk(table: Table) -> bool:
    cols = list(table.primary_key.columns)
    return len(cols) == 1 and isinstance(cols[0].type, Integer) and cols[0].autoincrement is True


def apply_tenancy(metadata) -> None:
    """Add ``company_id`` and make keys per company on every business table. Idempotent."""
    tables = [t for t in metadata.sorted_tables if t.name not in PLATFORM_TABLES]
    for table in tables:
        if "company_id" in table.c:
            continue
        keep_pk = _autoinc_pk(table)
        old_pk = list(table.primary_key.columns)
        col = Column("company_id", String(32), ForeignKey("companies.id"), nullable=False, index=True,
                     default=_company_from_context, primary_key=not keep_pk)
        table.append_column(col)
        if not keep_pk:
            for c in old_pk:
                c.autoincrement = False
            table.append_constraint(PrimaryKeyConstraint(col, *old_pk))
        # single-column UNIQUE -> unique per company
        for c in table.columns:
            if c.unique and c is not col:
                c.unique = False
                table.append_constraint(UniqueConstraint(col, c, name=f"uq_{table.name}_{c.name}_company"))

    by_name = {t.name: t for t in tables}
    for table in tables:
        for fk in list(table.foreign_keys):
            target = fk.column.table
            if target.name not in by_name or fk.parent.name == "company_id":
                continue
            # replace the single-column FK by (company_id, col) -> (company_id, target col)
            fk.parent.foreign_keys.discard(fk)
            table.foreign_keys.discard(fk)
            table.constraints.discard(fk.constraint)
            table.append_constraint(ForeignKeyConstraint(
                [table.c.company_id, fk.parent], [target.c.company_id, fk.column],
                name=f"fk_{table.name}_{fk.parent.name}_company"))


# ---- 2. scoped connections ---------------------------------------------------------------------

def scoped(engine: Engine, company_id: str) -> Engine:
    """The same engine (same pool), with every statement limited to ``company_id``."""
    return engine.execution_options(**{COMPANY_OPTION: company_id})


def _company_from(f):
    """``f`` itself when it is a company table (or an alias of one), else None."""
    if isinstance(f, Table):
        return f if is_company_table(f) else None
    if isinstance(f, Alias) and isinstance(f.element, Table):
        return f if is_company_table(f.element) else None
    return None  # subqueries / CTEs are scoped by their own SELECT


def _leftmost(f):
    while isinstance(f, Join):
        f = f.left
    return f


def _criteria(tables, company_id: str) -> tuple:
    return tuple(t.c.company_id == company_id for t in tables)


def scope_statement(stmt, company_id: str):
    """Return ``stmt`` with ``company_id = :company`` on every company table it reads or changes.

    The leftmost table of each FROM is filtered in WHERE; a joined table is filtered in its JOIN's
    ON clause, so a LEFT OUTER JOIN stays outer (a job without an invoice still shows).
    """

    def visit_join(join: Join) -> None:
        right = _company_from(_leftmost(join.right))
        if right is not None:
            join.onclause = and_(join.onclause, right.c.company_id == company_id)

    def visit_select(select: Select) -> None:
        # joins added with Select.join(): (target, onclause, left, flags) -> scope the ON clause
        joins = []
        for target, onclause, left, flags in select._setup_joins:
            t = _company_from(target)
            if t is not None and onclause is not None:
                onclause = and_(onclause, t.c.company_id == company_id)
            joins.append((target, onclause, left, flags))
        select._setup_joins = tuple(joins)
        tables = []
        for f in select.get_final_froms():
            t = _company_from(_leftmost(f))
            if t is not None and t not in tables:
                tables.append(t)
        if tables:
            select._where_criteria = select._where_criteria + _criteria(tables, company_id)

    def visit_dml(dml) -> None:
        if is_company_table(dml.table):
            dml._where_criteria = dml._where_criteria + _criteria([dml.table], company_id)

    return visitors.cloned_traverse(stmt, {}, {"join": visit_join, "select": visit_select,
                                               "update": visit_dml, "delete": visit_dml})


@event.listens_for(Engine, "before_execute", retval=True)
def _scope_before_execute(conn, clauseelement, multiparams, params, execution_options):
    company_id = execution_options.get(COMPANY_OPTION) or conn.get_execution_options().get(COMPANY_OPTION)
    if company_id and isinstance(clauseelement, (Select, Update, Delete)):
        clauseelement = scope_statement(clauseelement, company_id)
    return clauseelement, multiparams, params


# ---- 3. PostgreSQL row-level security (product database) ---------------------------------------

def rls_statements(metadata) -> list[str]:
    """SQL that turns on row-level security for every company table (PostgreSQL only).

    The app sets ``SET app.company_id = '<id>'`` per connection; a query that forgets the filter
    still sees only that company's rows.
    """
    out = []
    for table in metadata.sorted_tables:
        if not is_company_table(table):
            continue
        name = f'"{table.name}"'
        out += [
            f"ALTER TABLE {name} ENABLE ROW LEVEL SECURITY",
            f"ALTER TABLE {name} FORCE ROW LEVEL SECURITY",
            f"DROP POLICY IF EXISTS company_isolation ON {name}",
            f"CREATE POLICY company_isolation ON {name} USING (company_id = current_setting('app.company_id', true)) "
            f"WITH CHECK (company_id = current_setting('app.company_id', true))",
        ]
    return out
