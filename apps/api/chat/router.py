"""FastAPI routes for the chatbot: ``POST /api/chat`` and ``GET /api/chat/suggestions``.

Mounted by the API owner in ``app/main.py``: ``app.include_router(chat.router.router)``.
Endpoints are sync ``def`` so FastAPI runs them in a worker thread; the in-process API
client then calls back into the app on the server's event loop.

Per company (SPEC 6.4): the company is read from the request's scoped DB session (the same
dependency every other route uses; B1 scopes it from the login token), falling back to
``core.tenancy.default_company()``. Tools call the API with the caller's own ``Authorization``
and ``X-Role`` headers, so they see only that company's rows.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Header
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.deps import DB
from chat.api_client import InProcessApi
from chat.service import answer, suggestions
from core.tenancy import company_of, default_company

router = APIRouter(prefix="/api", tags=["Chat"])

Role = Literal["owner", "ppic", "design", "store", "production", "qc", "dispatch", "accounts", "marketing"]


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    history: list[ChatMessage] | None = None
    role: Role | None = None


def _role(x_role: str | None, body_role: str | None = None) -> str:
    # The header is the authority (SPEC 1); the body role is only a fallback.
    return (x_role or body_role or "owner").strip().lower()


def _company(db: Session | None) -> str:
    """The caller's company: only from the scoped session (token), never from the body (SPEC 6.2)."""
    return (company_of(db) if db is not None else None) or default_company()


@router.post("/chat")
def post_chat(req: ChatRequest, db: DB, x_role: str | None = Header(default=None),
              authorization: str | None = Header(default=None)) -> dict:
    role = _role(x_role, req.role)
    history = [m.model_dump() for m in req.history or []]
    company_id = _company(db)
    api = InProcessApi(role, authorization=authorization)
    reply = answer(req.message, role=role, history=history, api=api, company_id=company_id)
    return reply.to_dict()


@router.get("/chat/suggestions")
def get_chat_suggestions(x_role: str | None = Header(default=None)) -> dict:
    return suggestions(_role(x_role))
