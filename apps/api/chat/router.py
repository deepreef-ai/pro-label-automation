"""FastAPI routes for the chatbot: ``POST /api/chat`` and ``GET /api/chat/suggestions``.

Mounted by the API owner in ``app/main.py``: ``app.include_router(chat.router.router)``.
Endpoints are sync ``def`` so FastAPI runs them in a worker thread; the in-process API
client then calls back into the app on the server's event loop.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Header
from pydantic import BaseModel, Field

from chat.api_client import InProcessApi
from chat.service import answer, suggestions

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


@router.post("/chat")
def post_chat(req: ChatRequest, x_role: str | None = Header(default=None)) -> dict:
    role = _role(x_role, req.role)
    history = [m.model_dump() for m in req.history or []]
    reply = answer(req.message, role=role, history=history, api=InProcessApi(role))
    return reply.to_dict()


@router.get("/chat/suggestions")
def get_chat_suggestions(x_role: str | None = Header(default=None)) -> dict:
    return suggestions(_role(x_role))
