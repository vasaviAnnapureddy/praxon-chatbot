"""
Turning what the visitor said about timing into one factual label.

Read this file carefully, because it is the ethical centre of the project.

The bot does NOT score, rank, grade or qualify anyone. There is no "hot lead",
no star rating, no percentage. All this does is restate a fact the visitor
already told us, in consistent words, so the founder can sort a table.

The four labels, and nothing else:
    Immediate requirement (within a month)
    Planned requirement (1 to 3 months)
    Exploring options (3+ months or just researching)
    Details pending (timeline not shared)

"Details pending" is NOT a bad label. A visitor who did not mention timing may
be the best client of the year. The founder decides, every time.
"""

from __future__ import annotations

import re

LABEL_IMMEDIATE = "Immediate requirement"
LABEL_PLANNED = "Planned requirement"
LABEL_EXPLORING = "Exploring options"
LABEL_PENDING = "Details pending"

ALL_LABELS = [LABEL_IMMEDIATE, LABEL_PLANNED, LABEL_EXPLORING, LABEL_PENDING]

_IMMEDIATE = [
    r"within a month", r"this month", r"asap", r"as soon as possible",
    r"immediately", r"urgent", r"right away", r"start now", r"next week",
    r"in a week", r"2 weeks", r"two weeks", r"couple of weeks",
    r"\b(15|20|30)\s*days\b", r"1 month", r"one month",
    r"వెంటనే", r"తొందరగా", r"जल्दी", r"तुरंत", r"abhi", r"jaldi", r"ventane",
]
_PLANNED = [
    r"1 to 3 months", r"1-3 months", r"one to three months",
    r"2 months", r"two months", r"3 months", r"three months",
    r"next quarter", r"this quarter", r"in a couple of months",
    r"60 days", r"90 days",
]
_EXPLORING = [
    r"3\+ months", r"more than 3 months", r"after 3 months", r"4 months",
    r"5 months", r"6 months", r"six months", r"next year", r"later this year",
    r"just exploring", r"just looking", r"just researching", r"just checking",
    r"not decided", r"no timeline", r"no fixed", r"sometime", r"maybe later",
    r"planning stage", r"early stage", r"gathering information",
    r"చూస్తున్నాను", r"देख रहे", r"soch rahe", r"chustunna",
]

_IMMEDIATE_RE = re.compile("|".join(_IMMEDIATE), re.IGNORECASE)
_PLANNED_RE = re.compile("|".join(_PLANNED), re.IGNORECASE)
_EXPLORING_RE = re.compile("|".join(_EXPLORING), re.IGNORECASE)


def timeline_label(raw: str) -> str:
    """
    Order matters: exploring is checked before immediate, because
    "just exploring, maybe start next week" is exploring, not immediate.
    """
    text = (raw or "").strip()
    if not text:
        return LABEL_PENDING
    if _EXPLORING_RE.search(text):
        return LABEL_EXPLORING
    if _PLANNED_RE.search(text):
        return LABEL_PLANNED
    if _IMMEDIATE_RE.search(text):
        return LABEL_IMMEDIATE
    return LABEL_PENDING


def label_description(label: str) -> str:
    """The plain-English gloss shown next to the label in the dashboard."""
    return {
        LABEL_IMMEDIATE: "Said they need it within a month",
        LABEL_PLANNED: "Said 1 to 3 months",
        LABEL_EXPLORING: "Said 3+ months, or that they are still researching",
        LABEL_PENDING: "Did not mention a timeline",
    }.get(label, "")


FOUNDER_STATUSES = ["New", "Contacted", "In discussion", "Converted", "Not pursuing"]


def is_valid_status(value: str) -> bool:
    return value in FOUNDER_STATUSES
