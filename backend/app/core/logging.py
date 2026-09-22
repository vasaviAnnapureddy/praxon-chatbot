"""
Logging with personal data masked.

Issue #10 (privacy / DPDP basics) is handled here: an email or a phone number
that reaches a log line is rewritten before it is written anywhere. Logs get
read by whoever is debugging; visitors' contact details do not belong there.
"""

from __future__ import annotations

import logging
import re
import sys

from app.config import settings

_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# Indian mobiles with or without +91, and any 10+ digit run.
_PHONE = re.compile(r"(?:\+?91[\s\-]?)?\b\d{10,13}\b")


def mask_pii(text: str) -> str:
    """hello@praxontech.in -> he***@praxontech.in ; 9876543210 -> 98******10"""
    if not text:
        return text

    def _email(m: re.Match[str]) -> str:
        local, _, domain = m.group(0).partition("@")
        keep = local[:2] if len(local) > 2 else local[:1]
        return f"{keep}***@{domain}"

    def _phone(m: re.Match[str]) -> str:
        digits = re.sub(r"\D", "", m.group(0))
        if len(digits) < 8:
            return m.group(0)
        return f"{digits[:2]}{'*' * (len(digits) - 4)}{digits[-2:]}"

    return _PHONE.sub(_phone, _EMAIL.sub(_email, text))


class MaskingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg = mask_pii(str(record.msg))
            if record.args:
                record.args = tuple(
                    mask_pii(a) if isinstance(a, str) else a for a in record.args
                )
        except Exception:  # logging must never break the request
            pass
        return True


_CONFIGURED = False


def setup_logging() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return

    level = logging.DEBUG if settings.DEBUG else logging.INFO
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s %(name)-22s %(message)s", "%H:%M:%S")
    )
    handler.addFilter(MaskingFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # These two are chatty and tell us nothing we need.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("google_genai").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    setup_logging()
    return logging.getLogger(name)


class Timer:
    """
    Measures a block and logs how long it took.

    Section 6 says speed is non-negotiable, and you cannot fix what you do not
    measure. Every slow-capable step in the request is wrapped in one of these.

        with Timer("retrieve") as t:
            ...
        t.ms  ->  float
    """

    def __init__(self, label: str, logger: logging.Logger | None = None) -> None:
        self.label = label
        self.log = logger or get_logger("timing")
        self.ms = 0.0

    def __enter__(self) -> "Timer":
        import time

        self._t0 = time.perf_counter()
        return self

    def __exit__(self, *exc: object) -> None:
        import time

        self.ms = (time.perf_counter() - self._t0) * 1000
        self.log.info("%-18s %7.0f ms", self.label, self.ms)
