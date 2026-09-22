"""
Everything that decides "should this message reach the LLM at all".

Issues handled here: #3 (prompt injection and abuse), #4 (cost control),
#5 (spam and fake leads), #14 (public exposure).

Design rule: this file NEVER calls an LLM. Every check is a cheap string
operation, because a blocked message must cost nothing. An attacker hammering
"ignore your instructions" 500 times should burn zero API quota.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.config import get_company

# --- prompt injection -------------------------------------------------------
# These are patterns of ATTACK, not patterns of rudeness. A frustrated visitor
# typing in capitals is fine; someone trying to rewrite the system prompt is not.
INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?(your\s+|the\s+|previous\s+|above\s+)*(instructions|rules|prompt)",
    r"disregard\s+(all\s+)?(your\s+|the\s+|previous\s+)*(instructions|rules|prompt)",
    r"forget\s+(everything|all|your\s+instructions|what\s+you)",
    r"(show|reveal|print|repeat|output|display|tell\s+me)\s+(me\s+)?(your\s+)?(system\s+)?(prompt|instructions|rules|configuration)",
    r"what\s+(is|are)\s+your\s+(system\s+)?(prompt|instructions|initial\s+instructions)",
    r"you\s+are\s+(now|actually)\s+(a|an|not)\b",
    r"pretend\s+(you\s+are|to\s+be)\b",
    r"act\s+as\s+(if\s+you\s+are\s+)?(a|an)\s+",
    r"\bdeveloper\s+mode\b",
    r"\bjailbreak\b|\bDAN\s+mode\b",
    r"repeat\s+(everything\s+)?(above|after\s+me)",
    r"</?(system|instruction)>",
    r"new\s+(instructions|system\s+prompt)\s*:",
    r"from\s+now\s+on\s+(you|your)\b.*\b(will|must|are)\b",
]
_INJECTION_RE = re.compile("|".join(INJECTION_PATTERNS), re.IGNORECASE)

# --- off-topic work requests ------------------------------------------------
OFFTOPIC_PATTERNS = [
    r"\b(write|do|solve|complete)\s+(my|this|the)\s+(assignment|homework|essay|project\s+report|thesis)",
    r"\bwrite\s+(me\s+)?(a|an|some)?\s*(python|java|c\+\+|javascript|sql)\s+(code|program|script|function)\b",
    r"\b(cricket|ipl|football)\s+(score|match|result)",
    r"\b(weather|temperature)\s+(in|today|tomorrow)\b",
    r"\b(movie|song|recipe|joke|poem|shayari)\b",
    r"\bwho\s+(is|was)\s+the\s+(president|prime\s+minister|captain)\b",
    r"\btranslate\s+this\s+(paragraph|document|essay)\b",
    r"\bmy\s+(assignment|homework)\s+(is|due)\b",
]
_OFFTOPIC_RE = re.compile("|".join(OFFTOPIC_PATTERNS), re.IGNORECASE)

# --- spam -------------------------------------------------------------------
SPAM_PATTERNS = [
    r"https?://(?!(?:www\.)?(?:praxontech|cal\.com|wa\.me))",  # any external link
    r"\b(seo\s+services|backlinks|guest\s+post|buy\s+followers|crypto|forex|casino|betting)\b",
    r"\b(viagra|loan\s+offer|earn\s+\$?\d+\s+(daily|per\s+day))\b",
    r"(.)\1{15,}",                       # aaaaaaaaaaaaaaaaa
    r"^[^a-zA-Zऀ-ॿఀ-౿]{20,}$",  # pure symbols/numbers
]
_SPAM_RE = re.compile("|".join(SPAM_PATTERNS), re.IGNORECASE)

_GIBBERISH_RE = re.compile(r"^[bcdfghjklmnpqrstvwxyz]{8,}$", re.IGNORECASE)


@dataclass
class GuardVerdict:
    allow: bool
    reason: str = ""          # empty when allowed
    canned_reply: str = ""    # what to say instead, no LLM call needed
    flag: str = ""            # recorded on the message row for the dashboard


def _company_reply(key: str, default: str) -> str:
    return str(get_company().get(key, default))


def check_input(message: str, *, turns_so_far: int = 0) -> GuardVerdict:
    """
    Returns allow=False with a ready-made reply for anything that must not
    reach the model. The chat endpoint sends canned_reply and stops.
    """
    company = get_company()
    text = (message or "").strip()

    # --- empty ----------------------------------------------------------
    if not text:
        return GuardVerdict(
            False,
            "empty",
            "I didn't catch that — could you type your question?",
            "empty",
        )

    # --- too long (cost control) ----------------------------------------
    max_chars = int(company.get("chat.max_message_chars", 1200))
    if len(text) > max_chars:
        return GuardVerdict(
            False,
            "too_long",
            f"That's a long one. Could you shorten it to under {max_chars} characters, "
            "or send the key points? If it's detailed, it may be quicker to talk to the team directly.",
            "too_long",
        )

    # --- conversation length cap (cost control) -------------------------
    max_turns = int(company.get("chat.max_turns_per_session", 40))
    if turns_so_far >= max_turns:
        return GuardVerdict(
            False,
            "max_turns",
            "We've covered a lot here. At this point the team can help you far better than I can — "
            "shall I share their WhatsApp and booking link?",
            "max_turns",
        )

    # --- gibberish ------------------------------------------------------
    if len(text) < 4 and not text.isdigit():
        return GuardVerdict(
            False,
            "too_short",
            "Could you give me a little more? For example: \"do you build mobile apps?\"",
            "too_short",
        )
    if _GIBBERISH_RE.match(text.replace(" ", "")):
        return GuardVerdict(
            False,
            "gibberish",
            "I couldn't read that. Could you ask again — about our services, pricing or timelines?",
            "gibberish",
        )

    # --- prompt injection (issue #3) ------------------------------------
    if _INJECTION_RE.search(text):
        return GuardVerdict(
            False,
            "injection",
            f"I only answer questions about {company.name} — our services, how we work, "
            "timelines and pricing ranges. What would you like to know?",
            "injection",
        )

    # --- spam (issue #5) ------------------------------------------------
    if _SPAM_RE.search(text):
        return GuardVerdict(
            False,
            "spam",
            f"I can only help with questions about {company.name}. "
            "For business proposals, please email " + (company.sales_email or "the team") + ". "
            "Is there anything about our services I can help you with?",
            "spam",
        )

    # --- off-topic work (feature f) -------------------------------------
    if _OFFTOPIC_RE.search(text):
        return GuardVerdict(
            False,
            "offtopic",
            f"That's outside what I can help with — I'm {company.name}'s website assistant, "
            "so I stick to questions about the company and the work we do. "
            "Anything you'd like to know about our services?",
            "offtopic",
        )

    return GuardVerdict(True)


# --- contact validation (issue #5: fake leads) ------------------------------
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
_DISPOSABLE = {
    "mailinator.com", "10minutemail.com", "guerrillamail.com", "tempmail.com",
    "throwawaymail.com", "yopmail.com", "trashmail.com", "sharklasers.com",
}


def valid_email(value: str) -> bool:
    value = (value or "").strip().lower()
    if not _EMAIL_RE.match(value):
        return False
    domain = value.rsplit("@", 1)[-1]
    if domain in _DISPOSABLE:
        return False
    if value.startswith(("test@", "abc@", "asdf@", "aaa@")):
        return False
    return True


def valid_phone(value: str) -> bool:
    digits = re.sub(r"\D", "", value or "")
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    if len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) != 10:
        return False
    if digits[0] not in "6789":           # valid Indian mobile prefixes
        return False
    if len(set(digits)) <= 2:             # 9999999999, 1234512345
        return False
    if digits in {"1234567890", "9876543210"}:
        return False
    return True


def normalise_phone(value: str) -> str:
    digits = re.sub(r"\D", "", value or "")
    if len(digits) > 10:
        digits = digits[-10:]
    return digits
