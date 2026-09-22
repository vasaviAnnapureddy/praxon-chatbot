"""
/api/warmup — called the moment a visitor hovers or clicks the chat bubble.

Neon's compute pauses after 5 idle minutes and takes a second or two to come
back. If that wake-up happened on the visitor's first message, their first reply
would feel broken.

So the widget fires this when the bubble is opened — before they have typed a
word — and by the time they finish typing "do you build mobile apps?" the
database is already awake. The visitor never sees the delay.

/api/config is here too because it is the other thing the widget needs
immediately: colours, welcome text and quick questions, straight from
company.yaml. No database, so it is instant.
"""

from __future__ import annotations

import time

import asyncio

from fastapi import APIRouter

from app.config import get_company, settings
from app.core.logging import get_logger
from app.db.database import ping
from app.llm.provider import warm_connections

router = APIRouter(prefix="/api", tags=["warmup"])
log = get_logger("api.warmup")

_last_warm = 0.0
_WARM_COOLDOWN = 60.0  # don't hammer Neon if ten people open the chat at once


@router.post("/warmup")
async def warmup() -> dict[str, object]:
    global _last_warm
    now = time.time()

    if now - _last_warm < _WARM_COOLDOWN:
        return {"warm": True, "cached": True}

    t0 = time.perf_counter()
    # Wake Neon AND open the connections to Google at the same time.
    # gather() = "start both, wait for both" — total time is the slower one,
    # not the two added together.
    ok, _ = await asyncio.gather(ping(), warm_connections())
    took = int((time.perf_counter() - t0) * 1000)
    if ok:
        _last_warm = now
    log.info("warmup %s in %d ms", "ok" if ok else "FAILED", took)
    return {"warm": ok, "cached": False, "took_ms": took}


@router.get("/config")
async def widget_config() -> dict[str, object]:
    """
    Everything the browser is allowed to know. Note what is NOT here: no API
    keys, no database string, no prompts. Those never leave the server.
    """
    c = get_company()
    return {
        "company": {
            "name": c.name,
            "tagline": c.get("company.tagline", ""),
            "city": c.get("company.city", ""),
            "is_demo": bool(c.get("company.is_demo", False)),
            "demo_notice": c.get("company.demo_notice", ""),
        },
        "branding": c.get("branding", {}),
        "chat": {
            "bot_name": c.bot_name,
            "welcome_message": c.get("chat.welcome_message", ""),
            "launcher_greeting": c.get("chat.launcher_greeting", ""),
            "placeholder": c.get("chat.placeholder", "Type your question..."),
            "quick_questions": c.quick_questions,
            "max_message_chars": int(c.get("chat.max_message_chars", 1200)),
        },
        "contacts": {
            "whatsapp_link": c.whatsapp_link,
            "booking_url": c.booking_url,
            "sales_email": c.sales_email,
            "careers_email": c.careers_email,
            "phone_display": c.get("contacts.phone_display", ""),
            "office_line": c.get("contacts.office_line", ""),
            "response_promise": c.get("contacts.response_promise", ""),
            "linkedin_url": c.get("contacts.linkedin_url", ""),
        },
        "site": c.get("site", {}),
        # Public by design (see config.py). "" = the Google button stays hidden.
        "auth": {"google_client_id": settings.GOOGLE_CLIENT_ID},
        "services_preview": c.get("pricing_ranges", []),
    }
