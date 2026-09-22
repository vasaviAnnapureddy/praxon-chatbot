"""
Wires the nodes into one graph and compiles it once, at import time.

    guard -> language -> route -> retrieve -> lead_question -> compose -> END
       |
       +-- blocked? jump straight to compose (no LLM, no database, no cost)

Compiled once and reused for every request: compiling per request would add
milliseconds to every single message for no reason.

Why LangGraph at all, when this looks like a straight line? Two reasons that
pay off immediately: the conditional edge below skips four steps for blocked
traffic without a tangle of if-statements, and when Praxon later wants
"if intent == support, look up their ticket", it is one node and one edge, not
a rewrite of the chat endpoint.
"""

from __future__ import annotations

from langgraph.graph import END, StateGraph
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.graph.nodes import (
    compose_node,
    detect_language_node,
    guard_input_node,
    lead_question_node,
    retrieve_node,
    route_intent_node,
)
from app.graph.state import ConvState, new_state

log = get_logger("graph.builder")


def _after_guard(state: ConvState) -> str:
    return "compose" if state.get("blocked") else "language"


def build_graph():  # noqa: ANN201
    graph = StateGraph(ConvState)

    graph.add_node("guard", guard_input_node)
    graph.add_node("language", detect_language_node)
    graph.add_node("route", route_intent_node)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("lead_question", lead_question_node)
    graph.add_node("compose", compose_node)

    graph.set_entry_point("guard")
    graph.add_conditional_edges("guard", _after_guard, {"compose": "compose", "language": "language"})
    graph.add_edge("language", "route")
    graph.add_edge("route", "retrieve")
    graph.add_edge("retrieve", "lead_question")
    graph.add_edge("lead_question", "compose")
    graph.add_edge("compose", END)

    return graph.compile()


_compiled = None


def get_graph():  # noqa: ANN201
    global _compiled
    if _compiled is None:
        _compiled = build_graph()
        log.info("conversation graph compiled")
    return _compiled


async def plan_reply(
    session: AsyncSession,
    *,
    message: str,
    conversation_id: int,
    history: list[dict[str, str]],
    turns_so_far: int,
    asked_fields: list[str],
    skipped_fields: list[str],
    known_lead: dict,
    consent_shown: bool,
    prefetch: dict | None = None,
) -> ConvState:
    """
    Run the whole graph and hand back the plan.

    The plan either contains a finished `canned_reply` (blocked, careers,
    handoff, no-context) or a `system_prompt` + `user_prompt` for the chat
    endpoint to stream. Either way, no words have been generated yet — which is
    exactly why the first word can appear so fast.
    """
    state = new_state(
        message=message,
        conversation_id=conversation_id,
        history=history,
        turns_so_far=turns_so_far,
        asked_fields=asked_fields,
        skipped_fields=skipped_fields,
        known_lead=known_lead,
        consent_shown=consent_shown,
    )
    # prefetch: the search numbers chat.py started working out early — see
    # _start_prefetch() in api/chat.py and retrieve_node() in nodes.py.
    result = await get_graph().ainvoke(
        state, config={"configurable": {"session": session, "prefetch": prefetch or {}}}
    )
    return result  # type: ignore[return-value]
