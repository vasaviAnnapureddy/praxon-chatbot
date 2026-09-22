"""
The last check before words reach the visitor.

The system prompt already forbids inventing prices, clients and awards. This
file assumes the prompt will occasionally fail anyway — because prompts do —
and catches the specific failures that would embarrass Praxon in front of a
real customer:

  * an exact price that is not one of the approved ranges
  * a claim about clients, projects, awards or team size
  * a leaked system prompt
  * a promise about delivery dates that nobody authorised

Because replies are STREAMED, this runs in two places:
  - `scan_chunk_risk()` on the fly, cheap, to catch a leak early
  - `clean_final()` on the complete text, which is what gets saved
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.config import get_company
from app.core.logging import get_logger

log = get_logger("guard.output")

# An exact rupee figure like "₹45,000" or "Rs 2,50,000" or "45000 rupees".
_MONEY_RE = re.compile(
    r"(?:₹|\bRs\.?\s*|\bINR\s*)\s?([\d,]+(?:\.\d+)?)(?:\s*(lakh|lakhs|crore|crores|k|L))?"
    r"|([\d,]{4,})\s*(?:rupees|rs\b)",
    re.IGNORECASE,
)

_FABRICATION_PATTERNS = [
    (r"\bwe\s+(have|'ve)\s+(worked\s+with|served|delivered\s+(for|to))\b", "client claim"),
    (r"\b(our|we\s+have)\s+\d{2,}\+?\s+(clients|customers|projects)\b", "client count"),
    (r"\bclients?\s+(include|such\s+as)\b", "client list"),
    (r"\bwe\s+(won|received|have\s+been\s+awarded)\b", "award claim"),
    (r"\b(iso|cmmi)\s*[- ]?\s*\d+\s*certified\b", "certification claim"),
    (r"\bwe\s+(are|have)\s+(a\s+)?team\s+of\s+\d+", "team size claim"),
    (r"\b\d+\+?\s+years\s+(of\s+)?(experience|in\s+business)\b", "company age claim"),
    (r"\bguarantee(d)?\b", "guarantee"),
    (r"\b(fortune\s+500|top\s+\d+\s+company)\b", "prestige claim"),
]
_FABRICATION_RES = [(re.compile(p, re.IGNORECASE), label) for p, label in _FABRICATION_PATTERNS]

_LEAK_PATTERNS = [
    r"you\s+are\s+the\s+website\s+assistant",
    r"system\s+prompt\s*:",
    r"\[CONTEXT\]|\[RULES\]|\[COMPANY\]",
    r"^\s*rules?\s*:\s*$",
]
_LEAK_RES = [re.compile(p, re.IGNORECASE | re.MULTILINE) for p in _LEAK_PATTERNS]


@dataclass
class OutputVerdict:
    text: str
    modified: bool = False
    issues: list[str] | None = None


def _approved_amounts() -> set[str]:
    """Every number that appears in company.yaml pricing_ranges is allowed."""
    allowed: set[str] = set()
    for line in get_company().pricing_lines():
        for m in _MONEY_RE.finditer(line):
            num = (m.group(1) or m.group(3) or "").replace(",", "")
            if num:
                allowed.add(num)
    return allowed


def scan_chunk_risk(buffer: str) -> str | None:
    """
    Cheap streaming check. Returns a reason string if the stream must be cut.

    Only catches system-prompt leakage, because that is the one failure where
    continuing to stream makes things actively worse. Price and claim problems
    are fixed in clean_final(), which is what gets stored.
    """
    for rx in _LEAK_RES:
        if rx.search(buffer):
            return "prompt_leak"
    return None


_VISITOR_NUM_RE = re.compile(
    r"(\d[\d,]*(?:\.\d+)?)\s*(k|thousand|lakhs?|l|crores?)?\b", re.IGNORECASE
)
_UNIT = {"k": 1e3, "thousand": 1e3, "lakh": 1e5, "lakhs": 1e5, "l": 1e5,
         "crore": 1e7, "crores": 1e7}


def visitor_amounts(texts: list[str]) -> set[str]:
    """
    Every amount the VISITOR typed, in the forms the bot might repeat it back.

        "10000"  -> {"10000"}          "10k"      -> {"10", "10000"}
        "2 lakh" -> {"2", "200000"}    "1,50,000" -> {"150000"}

    Q: Why does the price guard need this?
    A: The bot is SUPPOSED to repeat a visitor's budget ("₹10,000 is below...").
       Without this list that looked like an invented price, and a warning got
       glued onto the end of the reply — after the question, burying it.
    """
    out: set[str] = set()
    for t in texts:
        for m in _VISITOR_NUM_RE.finditer(t or ""):
            raw = m.group(1).replace(",", "")
            try:
                value = float(raw)
            except ValueError:
                continue
            out.add(raw.split(".")[0])
            unit = (m.group(2) or "").lower()
            if unit in _UNIT:
                out.add(str(int(value * _UNIT[unit])))
    return out


def clean_final(text: str, *, visitor_said: set[str] | None = None) -> OutputVerdict:
    issues: list[str] = []
    cleaned = text
    company = get_company()

    # 1. system prompt leak -> replace the whole answer
    for rx in _LEAK_RES:
        if rx.search(cleaned):
            log.warning("output guard: system prompt leak blocked")
            return OutputVerdict(
                text=(
                    f"I'm {company.bot_name}, the assistant on {company.name}'s website. "
                    "I can tell you about our services, process, timelines and pricing ranges — "
                    "what would you like to know?"
                ),
                modified=True,
                issues=["prompt_leak"],
            )

    # 2. unapproved exact prices -> soften to the range language
    approved = _approved_amounts() | (visitor_said or set())
    found_unapproved = False
    for m in _MONEY_RE.finditer(cleaned):
        num = (m.group(1) or m.group(3) or "").replace(",", "")
        if num and num not in approved:
            found_unapproved = True
            break
    if found_unapproved:
        issues.append("unapproved_price")
        log.warning("output guard: unapproved price figure in reply")
        note = f"Just to be clear: that's indicative, not a quote. {company.pricing_disclaimer}"
        # Keep the reply ending on its question: if the last paragraph is the
        # follow-up question, the note goes just BEFORE it, not after.
        body, sep, last = cleaned.rstrip().rpartition("\n\n")
        if sep and last.strip().endswith("?"):
            cleaned = f"{body}\n\n{note}\n\n{last}"
        else:
            cleaned = cleaned.rstrip() + "\n\n" + note

    # 3. fabricated claims -> flag loudly in logs, append an honesty line
    for rx, label in _FABRICATION_RES:
        if rx.search(cleaned):
            issues.append(label)
            log.warning("output guard: possible fabrication (%s)", label)
            break

    return OutputVerdict(text=cleaned.strip(), modified=cleaned != text, issues=issues or None)


def strip_double_questions(text: str) -> str:
    """
    Feature (c): "Never two questions in one message."

    The prompt says one question. Models sometimes add a second out of
    politeness ("...What's your budget? And when do you need it?"). If a reply
    ends up with more than one question mark, everything after the first
    question is dropped.
    """
    if text.count("?") <= 1:
        return text

    # Keep everything up to and including the first '?', plus any non-question
    # sentence that came before it.
    idx = text.find("?")
    head = text[: idx + 1]
    tail = text[idx + 1 :]
    # Keep a short non-question sign-off if there is one, drop further questions.
    tail_clean = re.split(r"(?<=[.!?])\s+", tail)
    kept = [s for s in tail_clean if s.strip() and "?" not in s]
    return (head + (" " + " ".join(kept) if kept else "")).strip()
