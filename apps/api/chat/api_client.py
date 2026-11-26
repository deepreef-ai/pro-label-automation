"""In-process client for the public HTTP API, handed to chat tools as ``ToolContext.api``.

Calls go through ``httpx.AsyncClient`` + ``ASGITransport`` straight into the FastAPI app
(no network, no port) with the caller's ``X-Role`` header and, when the chat request carried
one, its ``Authorization`` header (SPEC 6.4: tools call the API with the user's token, so they
see only the signed-in company's rows), so every role check, company scope and business
rule of the real API applies to the chatbot too. The app is imported lazily to avoid an
import cycle (``app.main`` includes ``chat.router``).

``get`` never raises for HTTP errors: it returns ``{"error": detail, "status": code}`` so a
tool result can explain the problem. Lists are wrapped as ``{"items": [...]}``.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

log = logging.getLogger(__name__)


def _wrap(data: Any) -> dict:
    if isinstance(data, dict):
        return data
    if isinstance(data, list):
        return {"items": data, "total": len(data)}
    return {"value": data}


class InProcessApi:
    """``get(path)`` / ``post(path, body)`` against the FastAPI app with the caller's headers."""

    def __init__(self, role: str = "owner", app: Any = None, timeout: float = 20.0,
                 authorization: str | None = None):
        self.role = role or "owner"
        self._app = app
        self.timeout = timeout
        self.authorization = authorization

    @property
    def headers(self) -> dict:
        out = {"X-Role": self.role}
        if self.authorization:
            out["Authorization"] = self.authorization
        return out

    @property
    def app(self) -> Any:
        if self._app is None:
            from app.main import app  # lazy: app.main imports chat.router

            self._app = app
        return self._app

    async def _request(self, method: str, path: str, body: Any = None) -> dict:
        import httpx

        transport = httpx.ASGITransport(app=self.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://chat.local",
                                     timeout=self.timeout) as client:
            res = await client.request(method, path, json=body, headers=self.headers)
        try:
            data = res.json()
        except ValueError:
            data = {"value": res.text}
        if res.status_code >= 400:
            detail = data.get("detail") if isinstance(data, dict) else None
            return {"error": str(detail or res.reason_phrase), "status": res.status_code}
        return _wrap(data)

    def _run(self, method: str, path: str, body: Any = None) -> dict:
        try:
            import anyio.from_thread

            try:  # inside a FastAPI sync endpoint (AnyIO worker thread): use the server loop
                return anyio.from_thread.run(self._request, method, path, body)
            except RuntimeError:
                pass
            return asyncio.run(self._request(method, path, body))
        except Exception as exc:  # the demo must never break on a tool call
            log.warning("chat api %s %s failed: %s", method, path, exc)
            return {"error": str(exc), "status": 0}

    def get(self, path: str, *args: Any, **kwargs: Any) -> dict:
        return self._run("GET", path)

    def post(self, path: str, body: Any = None, *args: Any, **kwargs: Any) -> dict:
        # Present because SPEC 4b defines it; chat tools never call it (locked test 6).
        return self._run("POST", path, body)


class NullApi:
    """Used when the app cannot be imported (e.g. scripts): every read returns an error."""

    def __init__(self, role: str = "owner"):
        self.role = role

    def get(self, path: str, *args: Any, **kwargs: Any) -> dict:
        return {"error": "API not available", "status": 0}

    def post(self, path: str, body: Any = None, *args: Any, **kwargs: Any) -> dict:
        return {"error": "API not available", "status": 0}


def default_api(role: str) -> Any:
    try:
        import app.main  # noqa: F401
    except Exception as exc:
        log.warning("chat: app.main not importable (%s); tools run without data", exc)
        return NullApi(role)
    return InProcessApi(role)
