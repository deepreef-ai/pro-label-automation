"""FastAPI app (SPEC 1: ``app`` in ``apps/api/app/main.py``; every route starts with ``/api``).

Run locally:  ``uvicorn app.main:app --reload --app-dir apps/api``
"""
from __future__ import annotations

import os

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.routers import design, dispatch, jobs, marketing, masters, production, qc, shell, store

VERSION = "0.1.0"

app = FastAPI(title="Pro Labels API (demo)", version=VERSION)

_origins = os.environ.get("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _origins.split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RequestValidationError)
async def _validation_as_400(_request: Request, exc: RequestValidationError) -> JSONResponse:
    """SPEC 1: validation errors are 400 ``{"detail": "<message>"}`` (not FastAPI's 422 list)."""
    parts = []
    for err in exc.errors():
        loc = ".".join(str(x) for x in err.get("loc", ()) if x not in ("body", "query", "path"))
        parts.append(f"{loc}: {err.get('msg')}" if loc else str(err.get("msg")))
    return JSONResponse(status_code=400, content={"detail": "; ".join(parts) or "invalid request"})


for _module in (shell, masters, marketing, jobs, design, store, production, qc, dispatch):
    app.include_router(_module.router, prefix="/api")
