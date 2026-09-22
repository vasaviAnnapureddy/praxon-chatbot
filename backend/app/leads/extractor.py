"""
Pulls lead details out of a conversation — in the BACKGROUND, after the reply
has already been streamed to the visitor.

The ordering rule from section 6 and issue #15:

    1. save the user message          (so a restart cannot lose it)
    2. stream the reply               (visitor is happy)
    3. save the assistant message     (so a restart cannot lose it)
    4. THEN extract                   (visitor already left this step behind)

If Render kills the container during step 4, the lead row stays marked
`pending`, and `retry_pending()` finishes the job the next time the app boots.
Nothing is lost, ever — that is why extraction writes its own state to the
database instead of living in a variable.
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.core.logging import get_logger
from app.db import crud
from app.db.database import session_scope
from app.graph.prompts import EXTRACTION_PROMPT
from app.guardrails.input_guard import normalise_phone, valid_email, valid_phone
from app.leads.stages import timeline_label

log = get_logger("leads.extract")

MAX_ATTEMPTS = 3
_FIELD_KEYS = ["requirement", "budget", "timeline_raw", "name", "company_name", "email", "phone"]


def _parse_json(raw: str) -> dict[str, Any]:
    """Models sometimes wrap JSON in ```json fences. Take the first {...} block."""
    text = raw.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return {}
    try:
        data = json.loads(match.group(0))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _transcript(messages: list) -> str:
    lines = []
    for m in messages[-24:]:
        who = "Visitor" if m.role == "user" else "Assistant"
        lines.append(f"{who}: {m.content}")
    return "\n".join(lines)


def _clean(data: dict[str, Any], company_email: str, company_phone: str) -> dict[str, str]:
    """
    Validation layer (issue #5).

    An invalid email is dropped, not stored. A founder calling a fake number is
    worse than a founder seeing a blank field.
    """
    out: dict[str, str] = {}

    for key in _FIELD_KEYS:
        value = str(data.get(key) or "").strip()
        if not value or value.lower() in {"none", "null", "n/a", "not provided", "empty"}:
            continue
        out[key] = value[:500]

    email = out.get("email", "").lower()
    if email:
        if not valid_email(email) or email == (company_email or "").lower():
            log.info("dropped invalid or company email from extraction")
            out.pop("email", None)
        else:
            out["email"] = email

    phone = out.get("phone", "")
    if phone:
        digits = normalise_phone(phone)
        if not valid_phone(phone) or digits == normalise_phone(company_phone or ""):
            log.info("dropped invalid or company phone from extraction")
            out.pop("phone", None)
        else:
            out["phone"] = digits

    if out.get("name"):
        out["name"] = out["name"][:120].title()

    # The factual label — never a score.
    if out.get("timeline_raw"):
        out["timeline_label"] = timeline_label(out["timeline_raw"])

    return out


async def extract_for_conversation(conversation_id: int, *, session=None) -> None:  # noqa: ANN001
    """
    Entry point. Safe to call twice for the same conversation — it fills blanks
    and never overwrites what the visitor already told us.
    """
    own_session = session is None
    session = session or await session_scope()

    try:
        from app.config import get_company
        from app.llm.provider import ChatTurn, get_provider

        company = get_company()
        conversation = await crud.get_conversation_by_id(session, conversation_id)
        if not conversation:
            return

        messages = await crud.all_messages(session, conversation_id)
        if len([m for m in messages if m.role == "user"]) < 1:
            return

        lead = await crud.get_or_create_lead(session, conversation_id)
        if "careers" in (conversation.intents or []):
            lead.category = "careers"
            await session.commit()

        if lead.extraction_attempts >= MAX_ATTEMPTS:
            await crud.set_extraction_state(session, lead, "failed")
            log.warning("extraction gave up for conversation %s", conversation_id)
            return

        # The cap applies here too: extraction is an LLM call like any other.
        from app.core.rate_limit import check_and_count_llm_call

        allowed = await check_and_count_llm_call(session)
        if not allowed.allowed:
            log.warning("daily cap reached — extraction deferred for conversation %s", conversation_id)
            return  # stays "pending", retried on next boot

        result = await get_provider().complete(
            system="You extract facts from text and return strict JSON. Never invent values.",
            turns=[
                ChatTurn(
                    role="user",
                    content=EXTRACTION_PROMPT.format(conversation=_transcript(messages)),
                )
            ],
            max_tokens=400,
            temperature=0.0,
        )

        data = _parse_json(result.text)
        if not data:
            await crud.set_extraction_state(session, lead, "pending")
            log.warning("extraction returned unparseable output for conversation %s", conversation_id)
            return

        fields = _clean(
            data,
            company_email=company.sales_email,
            company_phone=str(company.get("contacts.whatsapp_number", "")),
        )

        lead, changed = await crud.update_lead_fields(session, lead, fields)

        #   Q: The spec says "never ask a skipped question again". Where is that now?
        #   A: Two places, both reliable: a question is never asked twice
        #      (conversation.asked_fields), and the chat's Skip button records a
        #      real skip. This file used to also let the AI GUESS what was
        #      skipped — it marked every field, even ones never asked, and the
        #      bot then stopped before asking for name and contact. Removed.

        await crud.set_extraction_state(session, lead, "done")
        log.info(
            "extracted conversation %s: changed=%s label=%s",
            conversation_id,
            changed or "nothing",
            lead.timeline_label,
        )

        # Remove the row if the visitor shared nothing.
        #   Q: Why was the row created at all, then?
        #   A: It is made BEFORE extraction as a "pending" marker, so a Render
        #      restart mid-extraction can be recovered on boot. Once extraction
        #      has finished, an empty marker has done its job. Leaving it turned
        #      every "hi" into an Enquiry and buried the real ones.
        #   Careers chats are kept even when empty — the spec wants them tagged.
        has_details = any([
            lead.requirement, lead.budget, lead.timeline_raw,
            lead.name, lead.company_name, lead.email, lead.phone,
        ])
        if not has_details and lead.category != "careers":
            await crud.delete_lead(session, lead.id, wipe_conversation=False)
            log.info("conversation %s shared no details — not an enquiry", conversation_id)
            return

        # Alert only when there is actually a way to reply to them, and only once.
        if lead.has_contact and not lead.alert_sent:
            from app.notify.email_alert import send_lead_alert

            sent = await send_lead_alert(lead, conversation, messages)
            if sent:
                await crud.mark_alert_sent(session, lead)

    except Exception as exc:  # noqa: BLE001
        log.exception("extraction failed for conversation %s: %s", conversation_id, exc)
        try:
            lead = await crud.get_lead(session, conversation_id)
            if lead:
                await crud.set_extraction_state(session, lead, "pending")
        except Exception:  # noqa: BLE001
            pass
    finally:
        if own_session:
            await session.close()


async def retry_pending() -> int:
    """
    Called once on startup (main.py lifespan).

    This is the bit that makes "Render may restart the service anytime"
    survivable: any extraction interrupted mid-flight is picked up here.
    """
    session = await session_scope()
    try:
        pending = await crud.pending_extractions(session, max_attempts=MAX_ATTEMPTS)
        if not pending:
            return 0
        log.info("retrying %d unfinished lead extractions", len(pending))
        for lead in pending:
            await extract_for_conversation(lead.conversation_id, session=session)
        return len(pending)
    finally:
        await session.close()
