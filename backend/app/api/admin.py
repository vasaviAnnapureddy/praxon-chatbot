"""
The founder's API: leads, conversations, stats, unanswered, CSV export.

Security notes (issue #14 — this sits on a public URL):
  * logging in lives in api/auth.py (rate limited, 8 tries per 15 minutes)
  * the password is never logged, never returned, never compared with ==
  * a wrong username and a wrong password give the identical error and take the
    same time, so the endpoint cannot be used to discover the username
  * every other route requires a valid bearer token

Every timestamp that leaves this file has been through to_ist_string() first
(issue #17). The founder should never see a UTC time.
"""
# username is admin
#password is Admin@123456
from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import require_team, user_payload
from app.core.logging import get_logger
from app.core.timezone import to_ist_string
from app.db import crud
from app.db.database import get_session
from app.db.models import User
from app.leads.stages import ALL_LABELS, FOUNDER_STATUSES, label_description

router = APIRouter(prefix="/api/admin", tags=["admin"])
log = get_logger("api.admin")

# Logging in now lives in api/auth.py (team AND customers, password AND Google).
# Every route below is guarded by require_team: owner or team member only.
# A customer's pass is refused here even though it is a valid pass.


@router.get("/me")
async def me(user: User = Depends(require_team)) -> dict:
    return {"user": user_payload(user)}


# =============================================================================
# Serialisers
# =============================================================================
def _lead_row(lead) -> dict[str, object]:  # noqa: ANN001
    return {
        "id": lead.id,
        "conversation_id": lead.conversation_id,
        "name": lead.name,
        "company_name": lead.company_name,
        "email": lead.email,
        "phone": lead.phone,
        "requirement": lead.requirement,
        "budget": lead.budget,
        "timeline_raw": lead.timeline_raw,
        "timeline_label": lead.timeline_label,
        "timeline_note": label_description(lead.timeline_label),
        "category": lead.category,
        "founder_status": lead.founder_status,
        "founder_notes": lead.founder_notes,
        "has_contact": lead.has_contact,
        "alert_sent": lead.alert_sent,
        "created_at": to_ist_string(lead.created_at),
        "updated_at": to_ist_string(lead.updated_at),
        "whatsapp_link": f"https://wa.me/91{lead.phone}" if lead.phone else "",
    }


def _message_row(msg) -> dict[str, object]:  # noqa: ANN001
    return {
        "id": msg.id,
        "role": msg.role,
        "content": msg.content,
        "intent": msg.intent,
        "blocked_reason": msg.blocked_reason,
        "latency_ms": msg.latency_ms,
        "created_at": to_ist_string(msg.created_at),
    }


def _conversation_row(conv) -> dict[str, object]:  # noqa: ANN001
    return {
        "id": conv.id,
        "session_id": conv.session_id,
        "message_count": conv.message_count,
        "language": conv.language,
        "intents": conv.intents or [],
        "started_at": to_ist_string(conv.started_at),
        "last_active_at": to_ist_string(conv.last_active_at),
    }


# =============================================================================
# Leads
# =============================================================================
@router.get("/leads")
async def list_leads(
    status_filter: str = "",
    category: str = "",
    timeline: str = "",
    limit: int = 200,
    offset: int = 0,
    _: User = Depends(require_team),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    rows = await crud.list_leads(
        session,
        status=status_filter,
        category=category,
        timeline=timeline,
        limit=min(limit, 500),
        offset=offset,
    )
    return {
        "leads": [_lead_row(r) for r in rows],
        "statuses": FOUNDER_STATUSES,
        "timeline_labels": ALL_LABELS,
    }


@router.get("/leads/{lead_id}")
async def lead_detail(
    lead_id: int,
    _: User = Depends(require_team),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    lead = await crud.get_lead_by_id(session, lead_id)
    if not lead:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lead not found")
    conv = await crud.get_conversation_by_id(session, lead.conversation_id)
    messages = await crud.all_messages(session, lead.conversation_id)
    return {
        "lead": _lead_row(lead),
        "conversation": _conversation_row(conv) if conv else None,
        "messages": [_message_row(m) for m in messages],
    }


class StatusUpdate(BaseModel):
    status: str
    notes: str | None = None


@router.patch("/leads/{lead_id}")
async def update_lead_status(
    lead_id: int,
    payload: StatusUpdate,
    _: User = Depends(require_team),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    if payload.status not in FOUNDER_STATUSES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Status must be one of: {', '.join(FOUNDER_STATUSES)}"
        )
    lead = await crud.set_founder_status(session, lead_id, payload.status, payload.notes)
    if not lead:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lead not found")
    return {"lead": _lead_row(lead)}


@router.delete("/leads/{lead_id}")
async def delete_lead(
    lead_id: int,
    _: User = Depends(require_team),
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    """Privacy deletion. Removes the lead AND the conversation behind it."""
    ok = await crud.delete_lead(session, lead_id, wipe_conversation=True)
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lead not found")
    log.info("lead %s deleted on request", lead_id)
    return {"status": "deleted"}


@router.get("/leads.csv")
async def export_csv(
    _: User = Depends(require_team),
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    """
    Backup layer 3 (section 7): the founder can pull everything out as a CSV at
    any moment, with no dependency on us, Render or Neon.
    """
    rows = await crud.list_leads(session, limit=5000)

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        ["Date (IST)", "Name", "Company", "Email", "Phone", "Requirement",
         "Budget", "Timeline said", "Timeline label", "Category", "Status", "Notes"]
    )
    for lead in rows:
        writer.writerow([
            to_ist_string(lead.created_at),
            lead.name, lead.company_name, lead.email, lead.phone,
            lead.requirement, lead.budget, lead.timeline_raw, lead.timeline_label,
            lead.category, lead.founder_status, lead.founder_notes,
        ])

    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="praxon-leads.csv"'},
    )


# =============================================================================
# Conversations, stats, unanswered
# =============================================================================
@router.get("/conversations")
async def list_conversations(
    limit: int = 100,
    offset: int = 0,
    _: User = Depends(require_team),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    rows = await crud.list_conversations(session, limit=min(limit, 300), offset=offset)
    return {"conversations": [_conversation_row(c) for c in rows]}


@router.get("/conversations/{conv_id}")
async def conversation_detail(
    conv_id: int,
    _: User = Depends(require_team),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    conv = await crud.get_conversation_by_id(session, conv_id)
    if not conv:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    messages = await crud.all_messages(session, conv_id)
    lead = await crud.get_lead(session, conv_id)
    return {
        "conversation": _conversation_row(conv),
        "messages": [_message_row(m) for m in messages],
        "lead": _lead_row(lead) if lead else None,
    }


@router.get("/stats")
async def stats(
    _: User = Depends(require_team),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    return await crud.dashboard_stats(session)


@router.get("/unanswered")
async def unanswered(
    include_resolved: bool = False,
    _: User = Depends(require_team),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    rows = await crud.list_unanswered(session, include_resolved=include_resolved)
    return {
        "questions": [
            {
                "id": r.id,
                "question": r.question,
                "times_asked": r.times_asked,
                "language": r.language,
                "last_asked_at": to_ist_string(r.last_asked_at),
                "resolved": r.resolved,
            }
            for r in rows
        ]
    }


@router.post("/unanswered/{item_id}/resolve")
async def resolve_unanswered(
    item_id: int,
    _: User = Depends(require_team),
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    ok = await crud.resolve_unanswered(session, item_id)
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    return {"status": "resolved"}


@router.post("/test-email")
async def test_email(_: User = Depends(require_team)) -> dict[str, object]:
    """One click to prove Resend is wired up, without waiting for a real lead."""
    from app.notify.email_alert import send_test_email

    ok, detail = await send_test_email()
    return {"sent": ok, "detail": detail}
