"""
/health — the endpoint cron-job.org pings every 10 minutes to stop Render sleeping.

THE ONE RULE FOR THIS FILE: it must never touch the database.

Neon's free plan gives 100 compute hours a month. A ping every 10 minutes is
4,320 pings a month. If each one woke Neon, the keep-alive designed to save the
app would quietly burn the database quota instead, and the whole thing would
stop working around the 20th of every month.

So: no imports of the database, no session dependency, no queries. It answers
from memory and returns in single-digit milliseconds.
"""

from __future__ import annotations

import time

from fastapi import APIRouter

from app.config import settings

router = APIRouter(tags=["health"])

_BOOTED_AT = time.time() #from how long this server is running


@router.get("/health")
async def health() -> dict[str, object]:
    return {
        "status": "ok",
        "service": "praxon-chatbot",
        "env": settings.APP_ENV,
        "uptime_seconds": int(time.time() - _BOOTED_AT),
    }


@router.head("/health")
async def health_head() -> dict[str, str]:
    # Some ping services send HEAD. Answer it rather than returning 405.
    return {}
