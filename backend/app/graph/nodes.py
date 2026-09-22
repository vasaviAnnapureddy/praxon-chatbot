"""
The steps of the conversation. Each one is small, named, and does one thing.

Speed rule that shaped this whole file (section 6): the LLM is the slowest thing
in the system, so every node tries to finish its job WITHOUT one. Language
detection is unicode ranges. Intent routing is keyword rules, and only falls
through to a model when the rules genuinely cannot tell. Careers, handoff and
blocked messages never reach a model at all.
"""

from __future__ import annotations

import re

from langchain_core.runnables import RunnableConfig

from app.config import get_company
from app.core.logging import get_logger
from app.graph import prompts
from app.graph.state import ConvState
from app.guardrails.input_guard import check_input
from app.rag.retriever import retrieve

log = get_logger("graph")


def _session(config: RunnableConfig):  # noqa: ANN202
    """LangGraph hands each node the config we passed into ainvoke()."""
    return (config or {}).get("configurable", {}).get("session")


# =============================================================================
# 1. Input guard
# =============================================================================
async def guard_input_node(state: ConvState, config: RunnableConfig) -> ConvState:
    verdict = check_input(state.get("message", ""), turns_so_far=state.get("turns_so_far", 0))
    if verdict.allow:
        return {"blocked": False}  # type: ignore[return-value]

    show_contacts = verdict.reason in {"max_turns", "too_long", "spam"}
    return {  # type: ignore[return-value]
        "blocked": True,
        "block_reason": verdict.reason,
        "canned_reply": verdict.canned_reply,
        "intent": "spam" if verdict.reason in {"spam", "injection"} else "offtopic",
        "use_llm": False,
        "show_contact_options": show_contacts,
    }


# =============================================================================
# 2. Language
# =============================================================================
_TELUGU = re.compile(r"[ఀ-౿]")
_DEVANAGARI = re.compile(r"[ऀ-ॿ]")

# Romanised Telugu / Hindi that arrives in Latin script (Tenglish / Hinglish).
_TENGLISH = {
    "enti", "entha", "ela", "ela unnaru", "kavali", "cheyyagalara", "cheyyali",
    "meeru", "nenu", "chala", "baga", "emi", "emiti", "ekkada", "eppudu",
    "ravali", "cheppandi", "telusa", "adugutunnanu", "kasta", "takkuva",
}
_HINGLISH = {
    "kya", "kitna", "kitne", "kaise", "kaisa", "hai", "hain", "chahiye", "karna",
    "karte", "mujhe", "aap", "apka", "aapka", "bata", "batao", "sakte", "nahi",
    "kab", "kahan", "banwana", "banana", "paisa", "rupaye",
}


async def detect_language_node(state: ConvState, config: RunnableConfig) -> ConvState:
    text = state.get("message", "")
    lower = text.lower()
    words = set(re.findall(r"[a-z]+", lower))

    has_telugu_script = bool(_TELUGU.search(text))
    has_devanagari = bool(_DEVANAGARI.search(text))
    has_latin = bool(re.search(r"[a-zA-Z]", text))

    if has_telugu_script:
        lang = "mixed-te" if has_latin else "te"
    elif has_devanagari:
        lang = "mixed-hi" if has_latin else "hi"
    elif words & _TENGLISH:
        lang = "mixed-te"
    elif words & _HINGLISH:
        lang = "mixed-hi"
    else:
        lang = "en"

    return {"language": lang}  # type: ignore[return-value]


# =============================================================================
# 3. Intent routing
# =============================================================================
_RULES: list[tuple[str, list[str]]] = [
    # Careers is checked FIRST and wins over everything. A job seeker must never
    # fall into the sales flow (feature e).
    ("careers", [
        "job", "jobs", "hiring", "vacancy", "vacancies", "opening", "openings",
        "internship", "intern", "resume", "cv", "career", "careers", "apply",
        "recruit", "fresher", "placement", "walk-in", "walkin", "naukri",
        "work at praxon", "work for you", "work with your team", "join your team",
        "join praxon", "salary", "stipend", "hr ",
        "उद्योग", "नौकरी", "ఉద్యోగ", "ఉద్యోగం",
    ]),
    ("human", [
        "talk to", "speak to", "speak with", "call me", "call you", "contact person",
        "human", "real person", "whatsapp", "phone number", "book a call", "meeting",
        "schedule a call", "connect me", "reach you", "contact you", "sales team",
    ]),
    ("pricing", [
        "price", "pricing", "cost", "charge", "charges", "budget", "quote",
        "how much", "rate", "rates", "fees", "expensive", "cheap", "afford",
        "ధర", "ఖర్చు", "कीमत", "कितना", "खर्च", "kitna", "entha",
    ]),
    ("process", [
        "nda", "contract", "agreement", "own the code", "owns the code", "ownership",
        "source code", "ip ", "intellectual property", "how do you work", "process",
        "milestone", "payment terms", "support", "maintenance", "after launch",
        "how long", "timeline", "duration", "how many weeks", "delivery",
    ]),
    ("trust", [
        "portfolio", "case study", "case studies", "clients", "experience",
        "why should i", "trust", "new company", "how old", "team size",
        "how many people", "references", "reviews", "proof",
    ]),
    ("services", [
        "services", "what do you do", "what do you build", "website", "web app",
        "mobile app", "android", "ios", "chatbot", "ai ", "automation", "cloud",
        "aws", "azure", "ecommerce", "e-commerce", "crm", "dashboard", "software",
        "develop", "build", "app ",
    ]),
    ("support", [
        "not working", "broken", "bug", "issue with", "error", "down",
        "existing project", "already a client",
    ]),
    ("smalltalk", [
        "hi", "hii", "hello", "hey", "good morning", "good evening", "thanks",
        "thank you", "thankyou", "ok", "okay", "bye", "namaste", "namaskaram",
    ]),
]

_LEAD_ANSWER_HINTS = re.compile(
    r"(₹|\brs\.?\b|\blakh\b|\bcrore\b|\bbudget\b|"
    r"\bwithin a month\b|\b1 to 3 months\b|\b3\+ months\b|\bjust exploring\b|"
    r"\bmy name is\b|\bi am \w+\b|@|\b\d{10}\b)",
    re.IGNORECASE,
)


def _rule_intent(message: str) -> str | None:
    lower = f" {message.lower().strip()} "

    for intent, keywords in _RULES:
        if not keywords:
            continue
        for kw in keywords:
            if intent == "smalltalk":
                # Smalltalk only counts if the message is basically just that word.
                if lower.strip() in {kw, kw + "!", kw + "."}:
                    return intent
            elif kw in lower:
                return intent
    return None


async def route_intent_node(state: ConvState, config: RunnableConfig) -> ConvState:
    if state.get("blocked"):
        return {}  # type: ignore[return-value]

    message = state.get("message", "")

    # Are they answering a question WE asked? Cheapest check, and it matters:
    # "10000" or "₹2 lakh" on its own must not be treated as a new question —
    # it would find nothing in the content and get "I don't have that in my notes".
    asked = set(state.get("asked_fields") or [])
    history = state.get("history") or []
    last_bot = next((h["content"] for h in reversed(history) if h.get("role") == "assistant"), "")

    # Two ways to recognise an answer:
    #   a) our last reply asked something, and this is short with no "?" of its own
    #        bot: "What budget are you working with?"   visitor: "10000"
    #   b) it contains a clear answer signal (₹, lakh, an email, a 10-digit number...)
    #   A message WITH a "?" is a new question, even if it also answers ours —
    #   "10k, do you do WordPress?" gets its question answered; the extractor
    #   still picks the budget out of it later.
    short_reply = len(message) < 120 and "?" not in message
    if asked and short_reply and ("?" in last_bot or _LEAD_ANSWER_HINTS.search(message)):
        return {"intent": "lead_answer", "intent_source": "rules"}  # type: ignore[return-value]

    rule_hit = _rule_intent(message)
    if rule_hit:
        return {"intent": rule_hit, "intent_source": "rules"}  # type: ignore[return-value]

    #   Q: The rules found nothing. Why not ask the AI to classify it?
    #   A: We used to. It cost ~1.1 s BEFORE the visitor saw a word, on every
    #      unclear message. And it bought almost nothing: spam, attacks and
    #      off-topic requests are already stopped by the input guard, and for
    #      everything else retrieval decides — if the content answers it, the AI
    #      answers from it; if not, the honest "I don't have that" path runs.
    #      So unclear messages are simply "general". Widen _RULES if a real
    #      category keeps being missed.
    return {"intent": "general", "intent_source": "default"}  # type: ignore[return-value]


# =============================================================================
# 4. Retrieval
# =============================================================================
_NO_RETRIEVAL_INTENTS = {"careers", "human", "spam", "offtopic", "smalltalk"}


async def retrieve_node(state: ConvState, config: RunnableConfig) -> ConvState:
    if state.get("blocked") or state.get("intent") in _NO_RETRIEVAL_INTENTS:
        return {"context": "", "retrieval_found": False}  # type: ignore[return-value]

    session = _session(config)
    if session is None:
        return {"context": "", "retrieval_found": False}  # type: ignore[return-value]

    query = state.get("message", "")

    # A short answer to our own question ("₹2 lakh") is a terrible search query.
    # Search with the previous question instead, so context stays relevant.
    if state.get("intent") == "lead_answer":
        history = state.get("history") or []
        previous_user = [h["content"] for h in history if h.get("role") == "user"]
        if previous_user:
            query = previous_user[-1]

    # chat.py started turning the likely search text into numbers the moment the
    # message arrived, in parallel with the database work. If it guessed the same
    # text we are searching with, use that result instead of waiting again.
    prefetch = (config or {}).get("configurable", {}).get("prefetch") or {}
    vector = None
    if prefetch.get("query") == query and prefetch.get("task") is not None:
        try:
            vector = await prefetch["task"]
        except Exception:  # noqa: BLE001 — fall back to embedding normally
            vector = None

    result = await retrieve(session, query, vector=vector)
    return {  # type: ignore[return-value]
        "context": result.context,
        "sources": result.sources,
        "retrieval_found": result.found,
        "retrieval_score": result.best_score,
        "timings": {**(state.get("timings") or {}), "retrieval_ms": result.took_ms},
    }


# =============================================================================
# 5. Which lead question (if any) to attach
# =============================================================================
_LEAD_OK_INTENTS = {"services", "pricing", "process", "trust", "general", "lead_answer"}

_FIELD_TO_LEAD_KEYS = {
    "requirement": ["requirement"],
    "budget": ["budget"],
    "timeline": ["timeline_raw"],
    "name": ["name"],
    "contact": ["email", "phone"],
}


# What the visitor just ASKED decides what we ask FIRST. A price question makes
# budget the natural next topic; "what do you build" makes their need the topic.
# After that, the normal order from company.yaml (ask_order) takes over.
_TIMELINE_WORDS = re.compile(r"\b(how long|timeline|how soon|when can|how many (weeks|days|months)|deadline)\b", re.I)


def _first_field_for(intent: str, message: str) -> str | None:
    if intent == "pricing":
        return "budget"
    if intent == "services":
        return "requirement"
    if intent == "process" and _TIMELINE_WORDS.search(message):
        return "timeline"
    return None


# --- Is the budget below our starting price? ---------------------------------
_MONEY_RE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(k|thousand|lakhs?|l|crores?)?\b", re.I)
_MONEY_UNIT = {"k": 1e3, "thousand": 1e3, "lakh": 1e5, "lakhs": 1e5, "l": 1e5, "crore": 1e7, "crores": 1e7}

# Which pricing line a conversation is about: (words in the chat, words in the
# pricing_ranges service name). Checked in this order — "web app" before "app".
_SERVICE_HINTS = [
    (re.compile(r"\b(dashboard|portal|web ?app|web application|crm|erp|software)\b", re.I), "web application"),
    (re.compile(r"\b(mobile|android|ios|app)\b", re.I), "mobile app"),
    (re.compile(r"\b(chat ?bot|ai|automation)\b", re.I), "chatbot"),
    (re.compile(r"\b(website|site|landing page|web ?page)\b", re.I), "website"),
]


def _rupees(text: str) -> float | None:
    """The largest amount in the text: "25k" -> 25000, "2 lakh" -> 200000, "Not sure" -> None."""
    values = []
    for number, unit in _MONEY_RE.findall(text or ""):
        value = float(number.replace(",", "")) * _MONEY_UNIT.get(unit.lower(), 1)
        if value >= 1000:                     # "5-8 pages", "2 weeks" are not budgets
            values.append(value)
    return max(values) if values else None


def _budget_below_range(state: ConvState) -> bool:
    """
    True when the visitor's budget is under the START of the matching price range.

      Q: Why decide this in code, not let the AI judge it?
      A: Because it changes WHICH question comes next (contact, not timeline),
         and that has to be decided before the reply is written. The AI still
         writes the words; the code only picks the path.
    """
    amount = _rupees(state.get("message", ""))
    if amount is None:
        return False
    starts: dict[str, float] = {}
    for item in get_company().get("pricing_ranges", []) or []:
        service, price_range = str(item.get("service", "")), str(item.get("range", ""))
        low = _rupees(price_range.split("–")[0].split("-")[0])
        if service and low and "month" not in price_range:     # monthly support is not a project
            starts[service.lower()] = low
    if not starts:
        return False
    chat = " ".join(h.get("content", "") for h in (state.get("history") or []) if h.get("role") == "user")
    for pattern, service_words in _SERVICE_HINTS:
        if pattern.search(chat):
            for name, low in starts.items():
                if service_words in name:
                    return amount < low
    return amount < min(starts.values())      # service unknown: the cheapest starting price


async def lead_question_node(state: ConvState, config: RunnableConfig) -> ConvState:
    """
    Decides whether to end this reply with ONE question, and which one.

    The conversation should keep moving: answer, then ask the natural next thing,
    one question per reply, from the very first reply.
        "how much for a website?" -> range ... "What budget are you working with?"
        "10000"                   -> honest reaction ... next question
        ...                       -> finally name + phone/email together

    Rules that still hold, all from the spec:
      - the question always comes AFTER the answer, never instead of it
      - never two questions in one message
      - never ask something twice, never re-ask something they skipped
      - never on careers, spam, off-topic or "talk to a human"
      - never right after "I don't know" — pushing for a budget after failing to
        answer is the worst possible moment
    """
    intent = state.get("intent", "general")
    if state.get("blocked") or intent not in _LEAD_OK_INTENTS:
        return {"lead_question_field": ""}  # type: ignore[return-value]

    asked = list(state.get("asked_fields") or [])
    skipped = set(state.get("skipped_fields") or [])
    known = state.get("known_lead") or {}

    # The field they are answering right now (only when intent is lead_answer).
    # compose_node uses it to tell the model HOW to react — see prompts.py.
    answered = asked[-1] if intent == "lead_answer" and asked else ""

    if not state.get("retrieval_found") and intent != "lead_answer":
        return {"lead_question_field": "", "answered_field": answered}  # type: ignore[return-value]

    company = get_company()
    order = list(company.ask_order)
    first = _first_field_for(intent, state.get("message", ""))
    if answered == "budget" and _budget_below_range(state):
        # Your rule: a low budget goes to the team quickly. Promise nothing,
        # ask for name + contact next (timeline can wait for the team's call).
        answered, first = "budget_low", "contact"
    if first and first in order:
        order.remove(first)
        order.insert(0, first)             # e.g. pricing -> budget jumps to the front

    for field in order:
        if field in asked or field in skipped:
            continue
        if any(known.get(k) for k in _FIELD_TO_LEAD_KEYS.get(field, [])):
            continue

        chips: list[str] = []
        if field == "budget":
            chips = company.budget_options
        elif field == "timeline":
            chips = company.timeline_options

        needs_consent = field in {"name", "contact"} and not state.get("consent_shown")

        return {  # type: ignore[return-value]
            "lead_question_field": field,
            "lead_question_text": prompts.lead_question_text(field),
            "quick_chips": chips,
            "show_consent": needs_consent,
            "answered_field": answered,
        }

    # Nothing left to ask — everything known, asked or skipped.
    return {"lead_question_field": "", "answered_field": answered}  # type: ignore[return-value]


# =============================================================================
# 6. Compose — build the final prompt, or the canned reply
# =============================================================================
async def compose_node(state: ConvState, config: RunnableConfig) -> ConvState:
    # --- already decided, no model needed -------------------------------
    if state.get("blocked"):
        return {"use_llm": False}  # type: ignore[return-value]

    intent = state.get("intent", "general")

    if intent == "careers":
        return {  # type: ignore[return-value]
            "use_llm": False,
            "canned_reply": prompts.careers_reply(),
            "lead_question_field": "",
            "show_contact_options": False,
        }

    if intent == "human":
        return {  # type: ignore[return-value]
            "use_llm": False,
            "canned_reply": prompts.human_handoff_reply(),
            "show_contact_options": True,
            "lead_question_field": "",
        }

    # --- nothing retrieved: honest fallback, still no model call ---------
    if not state.get("retrieval_found") and intent not in {"smalltalk", "lead_answer"}:
        return {  # type: ignore[return-value]
            "use_llm": False,
            "canned_reply": prompts.fallback_reply(),
            "show_contact_options": True,
            "lead_question_field": "",
            "block_reason": "no_context",
        }

    # --- normal path: build the prompt for the streaming model call ------
    field = state.get("lead_question_field", "")
    answered = state.get("answered_field", "")
    # answered -> how to react to what they just told us
    # field    -> the one question to end on ("" = a polite closing question instead)
    instruction = prompts.lead_instruction(field, answered=answered)
    if state.get("show_consent"):
        consent = get_company().get("chat.consent_line", "")
        if consent:
            instruction += f'\n\nBefore that question, add this exact line on its own: "{consent}"'

    system = prompts.build_system_prompt(state.get("context", ""), lead_instruction=instruction)

    return {  # type: ignore[return-value]
        "use_llm": True,
        "system_prompt": system,
        "user_prompt": state.get("message", ""),
    }
