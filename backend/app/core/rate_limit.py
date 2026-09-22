"""
Issue #4 (cost control) and issue #5 (spam) live here.

Three separate limits, deliberately:

1. Per-IP per-minute  — stops one person hammering the box. In memory: it only
   needs to be right for 60 seconds, and a Render restart resetting it is fine.
2. Per-IP per-day     — stops one person using the whole demo. Also in memory.
3. Daily LLM call cap — stops the PUBLIC LINK burning the API quota. This one
   lives in the DATABASE, because it must survive a Render restart. If it were
   in memory, anyone could reset the cap by making the service sleep and wake.

Login attempts are limited by the same per-IP machinery (issue #14).
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass

from app.config import get_company, settings
from app.core.logging import get_logger

log = get_logger("ratelimit")

# ip -> timestamps of recent hits
_minute_hits: dict[str, deque[float]] = defaultdict(deque)
_day_hits: dict[str, deque[float]] = defaultdict(deque)
_login_hits: dict[str, deque[float]] = defaultdict(deque)


@dataclass
class LimitResult:
    allowed: bool
    reason: str = ""
    retry_after_seconds: int = 0


def _prune(dq: deque[float], window_seconds: float) -> None:
    cutoff = time.time() - window_seconds
    while dq and dq[0] < cutoff:
        dq.popleft()


def client_ip(request) -> str:  # noqa: ANN001 - FastAPI Request, kept loose to avoid the import
    """
    Render sits behind a proxy, so request.client.host is the proxy.
    X-Forwarded-For's first entry is the real visitor.
    """
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return getattr(getattr(request, "client", None), "host", "") or "unknown"


def check_message_limits(ip: str) -> LimitResult:
    company = get_company()
    per_minute = int(company.get("limits.per_ip_messages_per_minute", 12))
    per_day = int(company.get("limits.per_ip_messages_per_day", 120))

    minute_dq = _minute_hits[ip]
    _prune(minute_dq, 60)
    if len(minute_dq) >= per_minute:
        wait = int(60 - (time.time() - minute_dq[0])) + 1
        return LimitResult(False, "too_fast", wait)

    day_dq = _day_hits[ip]
    _prune(day_dq, 86400)
    if len(day_dq) >= per_day:
        return LimitResult(False, "daily_visitor_cap", 3600)

    now = time.time()
    minute_dq.append(now)
    day_dq.append(now)
    return LimitResult(True)


def check_login_limits(ip: str, max_attempts: int = 8, window_seconds: int = 900) -> LimitResult:
    dq = _login_hits[ip]
    _prune(dq, window_seconds)
    if len(dq) >= max_attempts:
        wait = int(window_seconds - (time.time() - dq[0])) + 1
        log.warning("login rate limit hit for %s", ip)
        return LimitResult(False, "too_many_login_attempts", wait)
    dq.append(time.time())
    return LimitResult(True)


_request_hits: dict[str, deque[float]] = defaultdict(deque)


def check_access_request_limits(ip: str) -> LimitResult:
    """"Request access" form: 3 per hour per IP — enough for a real person, not for spam."""
    dq = _request_hits[ip]
    _prune(dq, 3600)
    if len(dq) >= 3:
        return LimitResult(False, "too_many_requests", int(3600 - (time.time() - dq[0])) + 1)
    dq.append(time.time())
    return LimitResult(True)


def clear_login_attempts(ip: str) -> None:
    """Called after a SUCCESSFUL login so a legitimate founder is not locked out."""
    _login_hits.pop(ip, None)


async def check_and_count_llm_call(session, *, tokens: int = 0) -> LimitResult:  # noqa: ANN001
    """
    The daily cap. Call this immediately BEFORE an LLM request.

    Returns allowed=False once the cap is reached, and the chat endpoint then
    replies with the contact-options fallback instead of calling the model.
    The public demo can therefore never cost more than one day's cap.
    """
    from app.db import crud  # imported here to keep this module import-light

    cap = int(settings.DAILY_LLM_CALL_CAP or 0)
    if cap <= 0:
        return LimitResult(True)

    used = await crud.increment_llm_usage(session, calls=1, tokens=tokens)
    if used > cap:
        log.error("DAILY LLM CAP REACHED (%s/%s) — serving fallbacks only", used, cap)
        return LimitResult(False, "daily_llm_cap")
    if used == int(cap * 0.8):
        log.warning("daily LLM usage at 80%% of cap (%s/%s)", used, cap)
    return LimitResult(True)
