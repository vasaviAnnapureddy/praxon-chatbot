"""
Signing in — ONE sign-in page for everybody who has a login.
Visitors never log in; the chatbot stays open to everyone.

    POST /api/auth/login           username-or-email + password
    POST /api/auth/google          "Continue with Google"
    GET  /api/auth/me              who am I?
    POST /api/auth/password        change my password (or choose one, after a temporary one)
    POST /api/auth/request-access  "Request access" form — no account is made, a person decides

After sign-in the ROLE decides where you go (the "home" in the reply):
    owner, team -> /admin      client -> /portal

A new account starts with a TEMPORARY password (made by the system, sent to the
person privately by whoever added them). Signing in with it gives a "setup"
pass that opens one thing only: choosing their own password.

  Q: Why does a wrong username and a wrong password give the SAME message?
  A: If they differed, anyone could test emails one by one to learn which
     ones have accounts. One message for every failure leaks nothing.
"""

from __future__ import annotations

import re

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.rate_limit import (
    check_access_request_limits,
    check_login_limits,
    clear_login_attempts,
    client_ip,
)
from app.core.security import (
    GoogleAuthError,
    create_access_token,
    decode_access_token,
    hash_password,
    password_strength_problem,
    verify_google_credential,
    verify_password,
)
from app.core.timezone import to_ist_string, utc_now
from app.db import crud
from app.db.database import get_session
from app.db.models import User
from app.notify.email_alert import send_access_request_alert

router = APIRouter(prefix="/api/auth", tags=["auth"])
log = get_logger("api.auth")
bearer = HTTPBearer(auto_error=False)

_WRONG = "Wrong login details"
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")


def home_for(role: str) -> str:
    """Where each role lands after signing in."""
    return "/portal" if role == "client" else "/admin"


def user_payload(user: User) -> dict:
    """What the browser is told about the logged-in person. Never the password hash."""
    return {
        "id": user.id,
        "name": user.name or user.username or user.email,
        "email": user.email or "",
        "username": user.username or "",
        "role": user.role,
        "company_name": user.company_name,
        "has_password": bool(user.password_hash),
        "must_change_password": user.must_change_password,
        "last_login": to_ist_string(user.last_login_at),
    }


def _limit(request: Request) -> str:
    """Same rate limit for both kinds of login: 8 tries per 15 minutes per IP."""
    ip = client_ip(request)
    verdict = check_login_limits(ip)
    if not verdict.allowed:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Too many attempts. Try again in {verdict.retry_after_seconds // 60 + 1} minutes.",
        )
    return ip


async def _finish_login(session: AsyncSession, user: User, ip: str) -> dict:
    clear_login_attempts(ip)
    await crud.record_login(session, user)
    log.info("%s signed in (%s)", user.name or user.username or user.email, user.role)
    return {
        "token": create_access_token(user.id, user.role),
        "user": user_payload(user),
        "home": home_for(user.role),
    }


# =============================================================================
# Logins
# =============================================================================
class LoginRequest(BaseModel):
    login: str = Field(min_length=1, max_length=200)      # username or email
    password: str = Field(min_length=1, max_length=200)


@router.post("/login")
async def login(
    payload: LoginRequest, request: Request, session: AsyncSession = Depends(get_session)
) -> dict:
    ip = _limit(request)
    user = await crud.find_user_for_login(session, payload.login)

    ok = (
        user is not None
        and user.is_active
        and bool(user.password_hash)                      # Google-only accounts have none
        and verify_password(payload.password, user.password_hash)
    )
    if not ok:
        log.warning("failed login from %s", ip)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, _WRONG)

    if user.must_change_password:
        #   Q: The password was right. Why refuse it when it's old?
        #   A: A temporary password lives in a WhatsApp chat. After 7 days
        #      unused it is safer dead; whoever added them makes a new one.
        #      Only someone who typed the right password ever sees this message.
        expires = user.temp_password_expires_at
        if expires is None or expires < utc_now():
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED,
                "This temporary password has expired. Ask the person who added you for a new one.",
            )
        clear_login_attempts(ip)
        # A "setup" pass: it opens the choose-your-password screen and nothing else.
        return {
            "token": create_access_token(user.id, user.role, scope="setup"),
            "user": user_payload(user),
            "must_change_password": True,
        }
    return await _finish_login(session, user, ip)


class GoogleRequest(BaseModel):
    credential: str = Field(min_length=20, max_length=5000)   # what Google's button returns


@router.post("/google")
async def google_login(
    payload: GoogleRequest, request: Request, session: AsyncSession = Depends(get_session)
) -> dict:
    ip = _limit(request)
    try:
        info = await verify_google_credential(payload.credential)
    except GoogleAuthError as exc:
        log.warning("google sign-in rejected from %s: %s", ip, exc)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Google sign-in failed. Please try again.")

    #   Q: Someone with a real Google account signs in. Why are they refused?
    #   A: Google only proves WHO they are. Whether they may come in is our
    #      decision: their email must already be added and active. No sign-ups.
    user = await crud.get_user_by_email(session, info["email"])
    if user is None or not user.is_active:
        log.warning("google sign-in for an email with no access, from %s", ip)
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            'This Google account has no access here. Use "Request access", or ask the Praxon team to add your email.',
        )

    # First Google login: remember Google's permanent id for this person.
    # After that, the id must match — so if someone later takes over this email
    # address with a DIFFERENT Google account, they are still refused.
    if user.google_sub and user.google_sub != info["sub"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This Google account does not match.")
    if not user.google_sub:
        user.google_sub = info["sub"]
    if not user.name and info["name"]:
        user.name = info["name"]
    if user.must_change_password:
        # Google has proved who they are, so the temporary password is not needed.
        # Kill it, so the WhatsApp copy is useless from now on.
        user.password_hash = ""
        user.must_change_password = False
        user.temp_password_expires_at = None
    return await _finish_login(session, user, ip)


# =============================================================================
# The guards every protected page uses
# =============================================================================
async def _user_from_pass(
    creds: HTTPAuthorizationCredentials | None, session: AsyncSession, *, allow_setup: bool
) -> tuple[User, str]:
    """Reads the pass, then checks the person still exists and is still active."""
    #   Q: The pass is signed. Why look the person up again on every request?
    #   A: So that switching someone off takes effect immediately, not when their
    #      12-hour pass happens to expire.
    if creds is None or not creds.credentials:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in")
    claims = decode_access_token(creds.credentials)
    if not claims:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired — sign in again")
    user = await crud.get_user(session, claims["uid"])
    if user is None or not user.is_active or user.role != claims["role"]:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired — sign in again")
    if claims["scope"] == "setup" and not allow_setup:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Choose your own password first")
    return user, claims["scope"]


async def current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    session: AsyncSession = Depends(get_session),
) -> User:
    """A normal, fully signed-in person. Setup passes are refused here."""
    user, _ = await _user_from_pass(creds, session, allow_setup=False)
    return user


async def require_team(user: User = Depends(current_user)) -> User:
    """Owner or team member. Every dashboard page uses this."""
    if user.role not in {"owner", "team"}:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Team access only")
    return user


async def require_owner(user: User = Depends(current_user)) -> User:
    """Only the owner — adding or switching off team members."""
    if user.role != "owner":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the owner can do this")
    return user


async def require_client(user: User = Depends(current_user)) -> User:
    """Only a customer. The portal uses this — and then filters to THEIR projects."""
    if user.role != "client":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Client access only")
    return user


# =============================================================================
# About me
# =============================================================================
@router.get("/me")
async def me(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    session: AsyncSession = Depends(get_session),
) -> dict:
    user, _ = await _user_from_pass(creds, session, allow_setup=True)
    return {"user": user_payload(user), "home": home_for(user.role)}


class PasswordChange(BaseModel):
    current: str = Field(default="", max_length=200)
    new: str = Field(min_length=1, max_length=200)


@router.post("/password")
async def change_password(
    payload: PasswordChange,
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """
    Two cases:
      - first sign-in with a temporary password -> choose your own. No "current"
        needed: they typed the temporary one a minute ago to get the setup pass.
      - a normal change -> the current password is required.
    """
    user, scope = await _user_from_pass(creds, session, allow_setup=True)
    first_time = user.must_change_password
    if scope == "setup" and not first_time:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired — sign in again")

    if not first_time and user.password_hash and not verify_password(payload.current, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is wrong")
    problem = password_strength_problem(payload.new)
    if problem:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, problem)
    if first_time and verify_password(payload.new, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Choose a new password, not the temporary one.")

    user.password_hash = hash_password(payload.new)
    user.must_change_password = False            # the temporary password is now dead
    user.temp_password_expires_at = None
    await session.commit()

    if first_time:
        # Setup finished: swap the setup pass for a normal one and send them home.
        log.info("%s chose their own password", user.name or user.email)
        return await _finish_login(session, user, client_ip(request))
    return {"status": "changed"}


# =============================================================================
# "Request access" — public. Stores a request; a person on the team decides.
# =============================================================================
class AccessRequestIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=200)
    company_name: str = Field(default="", max_length=160)
    message: str = Field(default="", max_length=1000)
    website: str = Field(default="", max_length=200)      # hidden trap field — see below


@router.post("/request-access")
async def request_access(
    payload: AccessRequestIn,
    request: Request,
    background: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
) -> dict:
    received = {"status": "received"}
    #   Q: What is the hidden "website" field?
    #   A: A trap for spam bots. People never see it, so they leave it empty.
    #      Bots fill every box. If it's filled we say "received" and save nothing.
    if payload.website:
        return received
    if not check_access_request_limits(client_ip(request)).allowed:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many requests. Please try again later.")
    email = payload.email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That email address doesn't look right")

    req = await crud.create_access_request(
        session,
        name=payload.name.strip(),
        email=email,
        company_name=payload.company_name.strip(),
        message=payload.message.strip(),
    )
    # The email goes out after the reply, so the person never waits on Resend.
    background.add_task(send_access_request_alert, req)
    #   Q: Why the same reply even if this email already has an account?
    #   A: A different reply would tell strangers which emails have accounts.
    return received
