"""
/api/chat — the streaming chat endpoint. This is the hot path.

Everything in section 6 (speed is non-negotiable) is enforced here:

  * Server-Sent Events, so the first word leaves as soon as the model produces
    it instead of waiting for the whole paragraph.
  * A `meta` event fires BEFORE the model is even called, so the browser can
    render the typing indicator and any chips immediately.
  * Quick-reply answers come from an in-memory cache — zero LLM, near-instant.
  * Lead extraction is a FastAPI BackgroundTask, queued after the response is
    finished, so it can never add a millisecond to the visitor's wait.
  * Every message is written to the database BEFORE the reply is generated, so
    a Render restart mid-reply loses nothing.

Note the database session is opened INSIDE the stream rather than with
`Depends(get_session)`. A dependency that fails does so before the response
exists, and the visitor gets a raw 500 with no way to reach anybody. Opening it
here means even "the database is unreachable" arrives as a normal chat message
with WhatsApp and booking buttons under it (issue #12).
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_company
from app.core.logging import get_logger
from app.core.rate_limit import check_and_count_llm_call, check_message_limits, client_ip
from app.db import crud
from app.db.database import get_session, session_scope
from app.graph import prompts
from app.graph.builder import plan_reply
from app.graph.nodes import _LEAD_ANSWER_HINTS, _rule_intent
from app.guardrails.input_guard import check_input
from app.guardrails.output_guard import (
    clean_final,
    scan_chunk_risk,
    strip_double_questions,
    visitor_amounts,
)
from app.leads.extractor import extract_for_conversation
from app.llm.embeddings import embed_query
from app.llm.provider import ChatTurn, get_provider

router = APIRouter(prefix="/api", tags=["chat"])
log = get_logger("api.chat")

HISTORY_TURNS = 8          # how much conversation the model sees
MAX_REPLY_TOKENS = 500     # short answers are fast answers


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=8, max_length=64)
    message: str = Field(default="", max_length=4000)


# =============================================================================
# Quick-reply cache
# =============================================================================
# The five quick questions are asked constantly and the answer never changes
# between visitors, so the second person to tap "What services do you offer?"
# gets the answer with no model call at all. Cleared on every deploy, which is
# exactly when the content might have changed.
_cache: dict[str, tuple[float, str]] = {}
_CACHE_TTL = 3600.0


def _cache_key(message: str, field: str = "") -> str:
    # The follow-up question is part of the reply, so it is part of the key:
    # "What services...?" ending in a budget question is a different reply
    # from the same answer ending in nothing.
    return " ".join(message.lower().split())[:120] + "|" + field


def _cache_get(message: str, field: str = "") -> str | None:
    key = _cache_key(message, field)
    hit = _cache.get(key)
    if not hit:
        return None
    stored_at, text = hit
    if time.time() - stored_at > _CACHE_TTL:
        _cache.pop(key, None)
        return None
    return text


def _cache_put(message: str, text: str, field: str = "") -> None:
    if len(_cache) > 200:
        _cache.clear()
    _cache[_cache_key(message, field)] = (time.time(), text)


def _is_cacheable(message: str, state: dict) -> bool:
    """
    Only cache replies that are the same for EVERYBODY: a quick-reply button,
    tapped as the visitor's first message.

      Q: The reply now ends with a follow-up question. Isn't that personal?
      A: Only from the second message on. On message one, nobody has told us
         anything yet, so every visitor who taps "How much does a website cost?"
         gets the same answer AND the same budget question. Safe to cache.
    """
    if state.get("lead_question_field") and state.get("turns_so_far", 0) > 0:
        return False
    quick = {q.lower().strip() for q in get_company().quick_questions}
    return message.lower().strip() in quick


# =============================================================================
# SSE helpers
# =============================================================================
def _sse(event: str, data: dict | str) -> str:
    payload = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


def _contact_payload() -> dict:
    c = get_company()
    return {
        "whatsapp": c.whatsapp_link,
        "booking": c.booking_url,
        "email": c.sales_email,
    }


def _chunk_text(text: str, size: int = 24) -> list[str]:
    """
    Splits a canned reply into small pieces so it types out like a real answer.
    Purely cosmetic — a canned reply is already complete — but consistency in
    the UI matters more than saving 30 lines of JavaScript.
    """
    out: list[str] = []
    buf = ""
    for word in text.split(" "):
        buf = f"{buf} {word}" if buf else word
        if len(buf) >= size:
            out.append(buf + " ")
            buf = ""
    if buf:
        out.append(buf)
    return out


def _fallback_frames(text: str, *, blocked: str) -> list[str]:
    """A complete, well-formed SSE response for any "we cannot continue" case."""
    frames = [
        _sse("meta", {"intent": "error", "contact_options": True, "contacts": _contact_payload()})
    ]
    frames += [_sse("token", {"t": piece}) for piece in _chunk_text(text)]
    frames.append(_sse("done", {"latency_ms": 0, "total_ms": 0, "blocked": blocked}))
    return frames


def _start_prefetch(message: str, history: list[dict], asked: list[str]) -> dict:
    """
    Starts turning the likely search text into numbers in the background.

    Returns {"query": text, "task": running job} — or {} when searching won't
    happen at all (blocked, careers, "talk to a human", "hi"), so no Google call
    is wasted. It must guess the SAME text retrieve_node will search with:
    usually the message itself, but for a short answer to our own question
    ("10000"), the visitor's previous question. A wrong guess costs nothing but
    speed — retrieve_node then simply embeds the right text itself.
    """
    if not check_input(message, turns_so_far=0).allow:
        return {}
    if _rule_intent(message) in {"careers", "human", "smalltalk"}:
        return {}

    query = message
    last_bot = next((h["content"] for h in reversed(history) if h["role"] == "assistant"), "")
    short_reply = len(message) < 120 and "?" not in message
    if asked and short_reply and ("?" in last_bot or _LEAD_ANSWER_HINTS.search(message)):
        previous_user = [h["content"] for h in history if h["role"] == "user"]
        if previous_user:
            query = previous_user[-1]

    # create_task = "start this now, I'll collect the result later"
    return {"query": query, "task": asyncio.create_task(embed_query(query))}


# =============================================================================
# The conversation itself (needs a working database session)
# =============================================================================
async def _conversation_stream(
    session: AsyncSession,
    *,
    payload: ChatRequest,
    request: Request,
    background: BackgroundTasks,
    message: str,
    ip: str,
    started: float,
) -> AsyncIterator[str]:
    # SPEED: everything before the first word costs a database trip (~145 ms
    # each from a laptop to Neon in Singapore, ~3 ms from Render). This section
    # used to make ~10 trips one after another. Now it makes 3, and the slowest
    # non-database step runs at the same time as them.

    # --- 1. conversation + its enquiry in ONE trip, then the history ------
    conversation, lead = await crud.load_for_chat(
        session,
        payload.session_id,
        ip=ip,
        user_agent=request.headers.get("user-agent", ""),
    )
    history_rows = await crud.recent_messages(session, conversation.id, limit=HISTORY_TURNS * 2)
    history = [{"role": m.role, "content": m.content} for m in history_rows]
    # Each finished turn saves 2 messages (visitor + bot), so the number of
    # earlier visitor messages is worked out here instead of costing a trip.
    turns_so_far = ((conversation.message_count or 0) + 1) // 2

    # --- 2. START turning the search text into numbers, right now ---------
    # ~470 ms at Google. It used to wait until every database trip had
    # finished. Now it runs WHILE the message is being saved below.
    prefetch = _start_prefetch(message, history, list(conversation.asked_fields or []))

    known_lead = (
        {
            "requirement": lead.requirement,
            "budget": lead.budget,
            "timeline_raw": lead.timeline_raw,
            "name": lead.name,
            "email": lead.email,
            "phone": lead.phone,
        }
        if lead
        else {}
    )

    # --- 2. SAVE THE USER MESSAGE FIRST ---------------------------------
    # Before any model call. A restart from here on cannot lose it.
    await crud.save_message(session, conversation, role="user", content=message[:4000])

    # If we started the search early, this message will almost certainly reach
    # the AI — so count it against the daily cap NOW, while Google is still
    # working on the search numbers, instead of as one more trip afterwards.
    # (If it then turns out not to need the AI, the cap is off by one. Harmless.)
    early_allowed = await check_and_count_llm_call(session) if prefetch else None

    # --- 3. run the graph (guard, route, retrieve, plan) -----------------
    try:
        state = await plan_reply(
            session,
            message=message,
            conversation_id=conversation.id,
            history=history,
            turns_so_far=turns_so_far,
            asked_fields=list(conversation.asked_fields or []),
            skipped_fields=list(conversation.skipped_fields or []),
            known_lead=known_lead,
            consent_shown=bool(conversation.consent_shown),
            prefetch=prefetch,
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("graph failed: %s", exc)
        for frame in _fallback_frames(prompts.error_reply(), blocked="graph_error"):
            yield frame
        return
    finally:
        # Not used (a careers question, a blocked message)? Stop it quietly.
        task = prefetch.get("task")
        if task is not None and not task.done():
            task.cancel()

    intent = state.get("intent", "general")
    # commit=False: saved together with the reply at the end, not as an extra
    # trip before the first word.
    await crud.touch_conversation(
        session, conversation, intent=intent, language=state.get("language", "en"), commit=False
    )

    # --- 4. meta event: the browser can draw chips NOW -------------------
    yield _sse(
        "meta",
        {
            "intent": intent,
            "language": state.get("language", "en"),
            "sources": state.get("sources", []),
            "chips": state.get("quick_chips", []),
            "lead_field": state.get("lead_question_field", ""),
            "contact_options": bool(state.get("show_contact_options")),
            "contacts": _contact_payload() if state.get("show_contact_options") else {},
        },
    )

    first_word_ms = 0
    full_text = ""

    # --- 5a. canned reply: blocked, careers, handoff, no-context ---------
    if not state.get("use_llm"):
        full_text = state.get("canned_reply") or prompts.fallback_reply()
        first_word_ms = int((time.perf_counter() - started) * 1000)
        for piece in _chunk_text(full_text):
            yield _sse("token", {"t": piece})
            await asyncio.sleep(0)

        if state.get("block_reason") == "no_context" and message:
            await crud.record_unanswered(session, message, state.get("language", "en"))

    # --- 5b. cached quick reply -----------------------------------------
    elif _is_cacheable(message, state) and (
        cached := _cache_get(message, state.get("lead_question_field", ""))
    ):
        full_text = cached
        first_word_ms = int((time.perf_counter() - started) * 1000)
        log.info("cache hit (%d ms): %s", first_word_ms, message[:40])
        for piece in _chunk_text(full_text):
            yield _sse("token", {"t": piece})
            await asyncio.sleep(0)

    # --- 5c. the real thing: stream from the model -----------------------
    else:
        allowed = early_allowed or await check_and_count_llm_call(session)
        if not allowed.allowed:
            full_text = prompts.cap_reached_reply()
            first_word_ms = int((time.perf_counter() - started) * 1000)
            for piece in _chunk_text(full_text):
                yield _sse("token", {"t": piece})
        else:
            turns = [
                ChatTurn(role=h["role"], content=h["content"]) for h in history[-HISTORY_TURNS:]
            ]
            turns.append(ChatTurn(role="user", content=message))

            try:
                async for piece in get_provider().stream(
                    system=state.get("system_prompt", ""),
                    turns=turns,
                    max_tokens=MAX_REPLY_TOKENS,
                    temperature=0.3,
                ):
                    if not full_text:
                        first_word_ms = int((time.perf_counter() - started) * 1000)
                        log.info("first word in %d ms (%s)", first_word_ms, intent)

                    full_text += piece

                    # Cheap streaming guard: cut immediately on a prompt leak.
                    if scan_chunk_risk(full_text):
                        log.warning("stream cut: output guard tripped")
                        full_text = clean_final(full_text).text
                        yield _sse("replace", {"t": full_text})
                        break

                    yield _sse("token", {"t": piece})

            except Exception as exc:  # noqa: BLE001
                # LlmError, a timeout, an exhausted quota — all end the same
                # way for the visitor: a sentence and a route to a human.
                log.error("llm failed: %s", exc)
                if not full_text:
                    full_text = prompts.error_reply()
                    yield _sse(
                        "meta", {"contact_options": True, "contacts": _contact_payload()}
                    )
                    for piece in _chunk_text(full_text):
                        yield _sse("token", {"t": piece})

    # --- 6. output guard on the complete text ----------------------------
    # Amounts the visitor typed may be repeated back — they are not invented prices.
    said = visitor_amounts([message] + [h["content"] for h in history if h["role"] == "user"])
    guarded = clean_final(full_text, visitor_said=said)
    final_text = strip_double_questions(guarded.text)
    if final_text != full_text:
        yield _sse("replace", {"t": final_text})

    total_ms = int((time.perf_counter() - started) * 1000)

    # --- 7. save the assistant message -----------------------------------
    await crud.save_message(
        session,
        conversation,
        role="assistant",
        content=final_text,
        intent=intent,
        blocked_reason=state.get("block_reason", ""),
        latency_ms=first_word_ms,
        total_ms=total_ms,
    )

    # Record that we asked, so it is never asked twice.
    if state.get("lead_question_field"):
        # Name is asked together with contact, so it counts as asked too.
        # Recorded FIRST, so "contact" stays the last entry — the next turn
        # reads the last entry to know what the visitor is answering.
        if state["lead_question_field"] == "contact":
            await crud.mark_field_asked(session, conversation, "name")
        await crud.mark_field_asked(session, conversation, state["lead_question_field"])
    if state.get("show_consent"):
        await crud.mark_consent_shown(session, conversation)

    if state.get("use_llm") and _is_cacheable(message, state) and final_text:
        _cache_put(message, final_text, state.get("lead_question_field", ""))

    yield _sse(
        "done",
        {
            "latency_ms": first_word_ms,
            "total_ms": total_ms,
            "intent": intent,
            "guard_issues": guarded.issues or [],
        },
    )

    # --- 8. AFTER the reply: extract in the background --------------------
    if intent not in {"spam", "offtopic"} and not state.get("blocked"):
        background.add_task(extract_for_conversation, conversation.id)


# =============================================================================
# The endpoint
# =============================================================================
@router.post("/chat")
async def chat(
    payload: ChatRequest,
    request: Request,
    background: BackgroundTasks,
) -> StreamingResponse:
    ip = client_ip(request)
    started = time.perf_counter()

    async def event_stream() -> AsyncIterator[str]:
        message = (payload.message or "").strip()

        # --- rate limit, before anything expensive or stateful ----------
        limit = check_message_limits(ip)
        if not limit.allowed:
            text = (
                "You're sending messages faster than I can keep up with. "
                "Give me a moment — or reach the team directly."
                if limit.reason == "too_fast"
                else "You've reached today's message limit for this demo assistant. "
                "The team is still reachable below."
            )
            for frame in _fallback_frames(text, blocked=limit.reason):
                yield frame
            return

        # --- open the database session ----------------------------------
        try:
            session = await session_scope()
        except Exception as exc:  # noqa: BLE001
            log.exception("could not open a database session: %s", exc)
            for frame in _fallback_frames(prompts.error_reply(), blocked="db_unavailable"):
                yield frame
            return

        try:
            async for frame in _conversation_stream(
                session,
                payload=payload,
                request=request,
                background=background,
                message=message,
                ip=ip,
                started=started,
            ):
                yield frame
        except Exception as exc:  # noqa: BLE001
            # Anything that got past the inner handlers — a dropped Neon
            # connection mid-conversation, most likely.
            log.exception("chat stream failed: %s", exc)
            for frame in _fallback_frames(prompts.error_reply(), blocked="stream_error"):
                yield frame
        finally:
            await session.close()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",   # stops any proxy buffering the stream
            "Connection": "keep-alive",
        },
        background=background,
    )


@router.post("/skip")
async def skip_lead_question(
    payload: ChatRequest,
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    """
    The visitor tapped "skip" on a chip row.

    Feature (c): "If the visitor skips or ignores a question, never ask it
    again in that conversation." The message field carries the field name.
    """
    conversation = await crud.get_or_create_conversation(session, payload.session_id)
    field = (payload.message or "").strip().lower()
    if field:
        await crud.mark_field_skipped(session, conversation, field)
    return {"status": "ok", "skipped": field}
