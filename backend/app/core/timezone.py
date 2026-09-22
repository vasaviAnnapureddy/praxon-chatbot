"""
Issue #17: the server runs in UTC, the founder lives in IST.

Rule for the whole codebase:
  * every timestamp STORED is timezone-aware UTC
  * every timestamp SHOWN to a human goes through to_ist_string()

No exceptions. A lead that arrives at 9:30 PM IST must not read as 4:00 PM in
the dashboard.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30), name="IST")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_ist(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        # Anything naive coming out of Postgres is UTC by our own convention.
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(IST)


def to_ist_string(dt: datetime | None, with_time: bool = True) -> str:
    if dt is None:
        return ""
    ist = to_ist(dt)
    return ist.strftime("%d %b %Y, %I:%M %p IST") if with_time else ist.strftime("%d %b %Y")


def ist_today_key() -> str:
    """
    The date key the daily LLM cap counts against.

    Deliberately the IST date, not the UTC date: the cap should reset at
    midnight in Hyderabad, not at 5:30 AM.
    """
    return to_ist(utc_now()).strftime("%Y-%m-%d")
