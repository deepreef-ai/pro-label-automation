"""Auth routes (SPEC 6.2, contract tag Auth): OTP, login, logout, who am I."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.deps import Me, unauthorized
from app.services import auth as svc

router = APIRouter(tags=["Auth"])


class OtpRequest(BaseModel):
    company_slug: str = ""
    login: str = Field(min_length=1)


class LoginRequest(BaseModel):
    company_slug: str = ""
    login: str = Field(min_length=1)
    otp: str = Field(pattern=r"^\d{6}$")


@router.post("/auth/otp")
def post_auth_otp(body: OtpRequest) -> dict:
    return svc.send_otp(body.company_slug, body.login)


@router.post("/auth/login")
def post_auth_login(body: LoginRequest) -> dict:
    session = svc.login(body.company_slug, body.login, body.otp)
    if session is None:
        raise unauthorized("wrong code, company or login")
    return session


@router.post("/auth/logout")
def post_auth_logout(me: Me) -> dict:
    svc.logout(me.token_id)
    return {"ok": True}


@router.get("/auth/me")
def get_auth_me(me: Me) -> dict:
    return svc.me(me)
