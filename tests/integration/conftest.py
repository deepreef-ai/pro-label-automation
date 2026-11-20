"""Fixtures for the API integration tests (LOCKED tests 4 and 5).

Each fixture builds a synthetic demo database (the full fixture story: JC-1301, the
LOCKED client CL-011, ...) in a temp SQLite file, points ``DATABASE_URL`` at it and
serves ``app.main.app`` through ``fastapi.testclient.TestClient``. No network.

``core.etl.build`` and ``app.main`` are imported inside the fixtures, so the other
integration tests (AI safety) still run while the API is being written.
"""
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

ROLES = ("owner", "ppic", "design", "store", "production", "qc", "dispatch", "accounts", "marketing")

# Pure modules that never hold DB state; everything else under these packages is
# re-imported per database so a module-level engine always matches DATABASE_URL.
_APP_PACKAGES = ("app", "agents", "chat", "core")
_KEEP = ("core.rules", "core.llm", "core.etl")


class RoleClient:
    """TestClient wrapper that sends the demo ``X-Role`` header (SPEC 1).

    ``role=None`` sends no header at all (the API must treat that as ``owner``).
    """

    def __init__(self, client):
        self.client = client
        self.app = client.app

    @property
    def app_state(self) -> dict:
        return dict(getattr(self.client, "app_state", {}) or {})

    def request(self, method: str, url: str, role: str | None = "owner", **kwargs):
        headers = dict(kwargs.pop("headers", None) or {})
        if role is not None:
            headers["X-Role"] = role
        return self.client.request(method, url, headers=headers, **kwargs)

    def get(self, url: str, role: str | None = "owner", **kwargs):
        return self.request("GET", url, role=role, **kwargs)

    def post(self, url: str, role: str | None = "owner", **kwargs):
        return self.request("POST", url, role=role, **kwargs)

    def put(self, url: str, role: str | None = "owner", **kwargs):
        return self.request("PUT", url, role=role, **kwargs)


def _forget_app_modules() -> None:
    for name in list(sys.modules):
        if name in _APP_PACKAGES or name.startswith(_KEEP):
            continue
        if name.split(".")[0] in _APP_PACKAGES:
            del sys.modules[name]


@contextmanager
def _api_on_fresh_db(db_dir: Path):
    db_url = f"sqlite:///{(db_dir / 'demo.db').as_posix()}"
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("DATABASE_URL", db_url)
        from core.etl.build import build_database

        build_database(db_url)  # raw_dir=None: synthetic demo story only
        _forget_app_modules()
        from fastapi.testclient import TestClient

        from app.main import app

        with TestClient(app) as client:
            yield RoleClient(client)


@pytest.fixture(scope="session")
def api(tmp_path_factory):
    """One shared API + synthetic DB for read-only contract checks."""
    with _api_on_fresh_db(tmp_path_factory.mktemp("api_db")) as client:
        yield client


@pytest.fixture
def fresh_api(tmp_path):
    """A brand-new synthetic DB for a test that writes (story flow, lock release)."""
    with _api_on_fresh_db(tmp_path) as client:
        yield client
