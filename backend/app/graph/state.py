"""
The shared box that every step of the conversation reads from and writes to.

LangGraph passes one dict between nodes. Using a TypedDict (not a free-form
dict) means the editor tells you when you typo a key, which matters because a
missing key in a streaming endpoint fails at the worst possible moment.

The graph stops after `compose`. Generation is NOT a node, on purpose: the reply
has to stream token by token to the browser, and a node that returns a finished
string cannot do that. So the graph does all the thinking, hands back a plan,
and the chat endpoint streams the model directly. Everything routing, guarding
and grounding still happens in the graph where it can be pointed at.
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict

Intent = Literal[
    "services",      # what do you build
    "pricing",       # cost questions
    "process",       # how do you work, NDA, ownership, support
    "trust",         # are you real, portfolio, experience
    "support",       # existing customer needs help
    "careers",       # jobs and internships -> skips the sales flow entirely
    "human",         # wants to talk to a person
    "lead_answer",   # they are answering one of our lead questions
    "smalltalk",     # hi / thanks / bye
    "offtopic",      # homework, cricket, weather
    "spam",
    "general",       # anything else about the company
]

LeadField = Literal["requirement", "budget", "timeline", "name", "contact"]


class ConvState(TypedDict, total=False):
    # --- input ---------------------------------------------------------
    message: str
    session_id: str
    conversation_id: int
    history: list[dict[str, str]]        # [{"role": "user"|"assistant", "content": ...}]
    turns_so_far: int
    asked_fields: list[str]
    skipped_fields: list[str]
    known_lead: dict[str, Any]           # what we already have, so we never re-ask
    consent_shown: bool

    # --- produced by the nodes ------------------------------------------
    blocked: bool
    block_reason: str
    canned_reply: str

    language: str                        # en | te | hi | mixed
    intent: str
    intent_source: str                   # "rules" or "llm" — useful when tuning speed

    context: str                         # retrieved chunks, formatted
    sources: list[str]
    retrieval_found: bool
    retrieval_score: float

    lead_question_field: str             # "" when we are not asking anything
    lead_question_text: str
    answered_field: str                  # the field the visitor is answering right now
    show_consent: bool
    show_contact_options: bool
    quick_chips: list[str]               # budget/timeline chips to render as buttons

    system_prompt: str
    user_prompt: str
    use_llm: bool                        # False = we already have the full reply
    timings: dict[str, int]


def new_state(**kwargs: Any) -> ConvState:
    base: ConvState = {
        "message": "",
        "history": [],
        "turns_so_far": 0,
        "asked_fields": [],
        "skipped_fields": [],
        "known_lead": {},
        "consent_shown": False,
        "blocked": False,
        "block_reason": "",
        "canned_reply": "",
        "language": "en",
        "intent": "general",
        "intent_source": "rules",
        "context": "",
        "sources": [],
        "retrieval_found": False,
        "retrieval_score": 0.0,
        "lead_question_field": "",
        "lead_question_text": "",
        "answered_field": "",
        "show_consent": False,
        "show_contact_options": False,
        "quick_chips": [],
        "system_prompt": "",
        "user_prompt": "",
        "use_llm": True,
        "timings": {},
    }
    base.update(kwargs)  # type: ignore[typeddict-item]
    return base
