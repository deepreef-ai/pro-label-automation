"""Database engine, session and declarative base (SQLAlchemy 2.x, SPEC section 1).

* URL from env ``DATABASE_URL``; default ``sqlite:///data/demo.db`` (relative to the
  current working directory, normally the repo root). The parent folder of a SQLite
  file is created on demand.
* Only portable types and SQL are used, so the same models run on Postgres.
* SQLite connections switch ``PRAGMA foreign_keys=ON`` so FKs are enforced like Postgres.
"""
from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

DEFAULT_URL = "sqlite:///data/demo.db"


class Base(DeclarativeBase):
    """Declarative base for every model in ``core.models``."""


def database_url(url: str | None = None) -> str:
    """Resolve the database URL: explicit argument, else ``DATABASE_URL``, else the default."""
    return url or os.environ.get("DATABASE_URL") or DEFAULT_URL


def _sqlite_fk_on(dbapi_conn, _record) -> None:  # pragma: no cover - driver callback
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


def get_engine(url: str | None = None, **kwargs) -> Engine:
    """Create an engine for ``url`` (or ``DATABASE_URL`` / the default SQLite file).

    For a SQLite file the parent directory is created. Foreign keys are enforced.
    """
    resolved = database_url(url)
    u = make_url(resolved)
    is_sqlite = u.get_backend_name() == "sqlite"
    if is_sqlite:
        db = u.database
        if db and db != ":memory:" and not db.startswith("file:"):
            Path(db).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        kwargs.setdefault("connect_args", {"check_same_thread": False})
    engine = create_engine(resolved, future=True, **kwargs)
    if is_sqlite:
        event.listen(engine, "connect", _sqlite_fk_on)
    return engine


_engine: Engine | None = None


def engine() -> Engine:
    """Process-wide engine for the configured URL (created lazily)."""
    global _engine
    if _engine is None:
        _engine = get_engine()
    return _engine


class _LazySessionMaker:
    """``SessionLocal()`` bound lazily to :func:`engine`, so importing this module never connects."""

    _maker: sessionmaker | None = None

    def configure(self, bind: Engine) -> None:
        self._maker = sessionmaker(bind=bind, autoflush=False, expire_on_commit=False, future=True)

    def __call__(self, **kw) -> Session:
        if self._maker is None:
            self.configure(engine())
        return self._maker(**kw)  # type: ignore[misc]


SessionLocal = _LazySessionMaker()


def get_session(company_id: str | None = None) -> Iterator[Session]:
    """FastAPI dependency: ``def route(db: Session = Depends(get_session))``.

    The session sees and writes only one company's rows (SPEC 6, ``core.tenancy``). Until login
    lands (B1 #53) that is the demo company (``CO-001``); B1 passes the company from the token.
    """
    from core.tenancy import default_company, scoped

    session = SessionLocal(bind=scoped(engine(), company_id or default_company()))
    try:
        yield session
    finally:
        session.close()


def init_db(bind: Engine | None = None, drop: bool = False) -> Engine:
    """Create every table from ``core.models`` (optionally dropping them first)."""
    from core import models  # noqa: F401  (registers the mappers on Base.metadata)

    eng = bind or engine()
    if drop:
        Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    return eng
