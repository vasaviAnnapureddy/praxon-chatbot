"""
Tests ONLY your Google Gemini key. No database needed.

    python backend/scripts/check_gemini.py

Why this exists: if the chatbot fails, the cause could be the key, the model
name, or Neon. This checks the first two alone, so you know where to look.

It never prints your key — only its first 4 and last 4 characters.
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

# Lets this script find the `app` folder when run from the project root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402


def ok(msg: str) -> None:
    print(f"  [ OK ]  {msg}")


def fail(msg: str, fix: str) -> None:
    print(f"  [FAIL]  {msg}")
    print(f"          fix: {fix}")
    sys.exit(1)                         # stop here — later checks would only fail too


async def main() -> None:
    print("\nChecking your Google Gemini setup\n")

    # --- 1. is the key there at all? ------------------------------------------
    key = settings.GEMINI_API_KEY.strip()
    if not key or key == "your-gemini-key":
        fail("GEMINI_API_KEY is empty or still the placeholder",
             "paste your key into backend/.env as GEMINI_API_KEY=AQ....")
    # Google's key formats:
    #   AQ.   -> the current "Auth key" format AI Studio issues since mid-2026
    #   AIza  -> the older "Standard key", being retired by Google in Sept 2026
    if not key.startswith(("AQ.", "AIza")):
        fail("key starts with neither 'AQ.' nor 'AIza' — probably copied wrong",
             "copy it again from aistudio.google.com/apikey")
    if key.startswith("AIza"):
        print("  [WARN]  this is an older AIza key; Google is retiring these —"
              " make a new one (it will start with AQ.) if calls start failing")
    ok(f"key found: {key[:4]}...{key[-4:]}  ({len(key)} characters)")
    ok(f"chat model:      {settings.GEMINI_MODEL}")
    ok(f"embedding model: {settings.GEMINI_EMBED_MODEL}  (asking for {settings.EMBED_DIM} numbers)")

    # --- 2. embeddings: the thing ingest.py needs --------------------------------
    from app.llm.embeddings import embed_query

    try:
        t0 = time.perf_counter()
        vector = await embed_query("మీరు మొబైల్ యాప్‌లు చేస్తారా?")   # Telugu: "do you build mobile apps?"
        ms = (time.perf_counter() - t0) * 1000
    except Exception as exc:  # noqa: BLE001
        text = str(exc)
        if "API key not valid" in text or "API_KEY_INVALID" in text:
            fail("Google rejected the key", "create a fresh key at aistudio.google.com/apikey")
        if "not found" in text.lower() or "404" in text:
            fail(f"model '{settings.GEMINI_EMBED_MODEL}' not found — Google may have retired it",
                 "check ai.google.dev/gemini-api/docs/embeddings and update GEMINI_EMBED_MODEL")
        if "429" in text or "quota" in text.lower():
            fail("quota / rate limit hit", "wait a minute and retry; check usage in AI Studio")
        fail(f"embedding failed: {text[:200]}", "read the message above")

    if len(vector) != settings.EMBED_DIM:
        fail(f"got {len(vector)} numbers, expected {settings.EMBED_DIM}",
             "EMBED_DIM in backend/.env must be 768")
    ok(f"embedding works: Telugu text -> {len(vector)} numbers in {ms:.0f} ms")

    # --- 3. chat: the thing that writes replies ----------------------------------
    from app.llm.provider import ChatTurn, get_provider

    try:
        t0 = time.perf_counter()
        first_word_ms = None
        reply = ""
        async for piece in get_provider().stream(
            system="Reply in one short sentence.",
            turns=[ChatTurn(role="user", content="Say hello to a website visitor.")],
            max_tokens=40,
        ):
            if first_word_ms is None:
                first_word_ms = (time.perf_counter() - t0) * 1000
            reply += piece
    except Exception as exc:  # noqa: BLE001
        text = str(exc)
        if "not found" in text.lower() or "404" in text:
            fail(f"model '{settings.GEMINI_MODEL}' not found — Google may have retired it",
                 "check ai.google.dev/gemini-api/docs/models and update GEMINI_MODEL")
        fail(f"chat failed: {text[:200]}", "read the message above")

    ok(f"chat works: first word in {first_word_ms:.0f} ms  (target: under 1500)")
    print(f"          reply: \"{reply.strip()[:80]}\"")

    print("\nGoogle setup is working. Next: fill DATABASE_URL and run ingest.py\n")


if __name__ == "__main__":
    asyncio.run(main())
