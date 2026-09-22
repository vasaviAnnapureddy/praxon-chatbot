"""
One interface, three backends. Switch with LLM_PROVIDER in .env — nothing else
in the codebase knows or cares which model is answering.

Why a wrapper instead of calling Gemini directly:
  * If Gemini's free quota runs out mid-pitch, one .env line moves to Claude.
  * The eval script can run the same 50 questions against all three.
  * Every LLM call funnels through ONE place, which is where the timeout, the
    retry and the graceful fallback message live (issue #12).

Why Gemini is the default: one API key covers both generation and multilingual
embeddings (Telugu and Hindi included), the Flash-class model is fast enough for
the 1 to 1.5 second first-word target, and the free tier is generous.

Every method here is async. A blocking SDK call inside FastAPI would stall every
other visitor on a 0.1 CPU box.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from app.config import settings
from app.core.logging import get_logger

log = get_logger("llm")

REQUEST_TIMEOUT_SECONDS = 25.0
STREAM_FIRST_TOKEN_TIMEOUT = 12.0


@dataclass
class ChatTurn:
    role: str          # "user" | "assistant"
    content: str


@dataclass
class LlmResult:
    text: str
    tokens: int = 0
    provider: str = ""
    error: str = ""
    meta: dict[str, Any] = field(default_factory=dict)


class LlmError(RuntimeError):
    pass


# =============================================================================
# Base
# =============================================================================
class BaseProvider:
    name = "base"

    async def complete(
        self, *, system: str, turns: list[ChatTurn], max_tokens: int = 700, temperature: float = 0.3
    ) -> LlmResult:
        raise NotImplementedError

    async def stream(
        self, *, system: str, turns: list[ChatTurn], max_tokens: int = 700, temperature: float = 0.3
    ) -> AsyncIterator[str]:
        raise NotImplementedError
        yield ""  # pragma: no cover - makes the signature an async generator


# =============================================================================
# Gemini (default)
# =============================================================================
class GeminiProvider(BaseProvider):
    name = "gemini"

    def __init__(self) -> None:
        if not settings.GEMINI_API_KEY:
            raise LlmError("GEMINI_API_KEY is not set in backend/.env")
        from google import genai  # imported lazily: keeps startup fast

        self._genai = genai
        self._client = genai.Client(api_key=settings.GEMINI_API_KEY)
        self._model = settings.GEMINI_MODEL

    def _contents(self, turns: list[ChatTurn]) -> list[dict[str, Any]]:
        # Gemini calls the assistant "model".
        return [
            {"role": "model" if t.role == "assistant" else "user", "parts": [{"text": t.content}]}
            for t in turns
            if t.content
        ]

    def _config(self, system: str, max_tokens: int, temperature: float):  # noqa: ANN202
        from google.genai import types

        return types.GenerateContentConfig(
            system_instruction=system,
            temperature=temperature,
            max_output_tokens=max_tokens,
            # Short prompts + short answers = fast answers.
            candidate_count=1,
        )

    async def complete(
        self, *, system: str, turns: list[ChatTurn], max_tokens: int = 700, temperature: float = 0.3
    ) -> LlmResult:
        try:
            resp = await asyncio.wait_for(
                self._client.aio.models.generate_content(
                    model=self._model,
                    contents=self._contents(turns),
                    config=self._config(system, max_tokens, temperature),
                ),
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except TimeoutError as exc:
            raise LlmError("gemini timed out") from exc
        except Exception as exc:  # noqa: BLE001
            raise LlmError(f"gemini error: {exc}") from exc

        usage = getattr(resp, "usage_metadata", None)
        return LlmResult(
            text=(resp.text or "").strip(),
            tokens=int(getattr(usage, "total_token_count", 0) or 0),
            provider=self.name,
        )

    async def stream(
        self, *, system: str, turns: list[ChatTurn], max_tokens: int = 700, temperature: float = 0.3
    ) -> AsyncIterator[str]:
        try:
            iterator = await self._client.aio.models.generate_content_stream(
                model=self._model,
                contents=self._contents(turns),
                config=self._config(system, max_tokens, temperature),
            )
            async for chunk in iterator:
                piece = getattr(chunk, "text", None)
                if piece:
                    yield piece
        except Exception as exc:  # noqa: BLE001
            raise LlmError(f"gemini stream error: {exc}") from exc


# =============================================================================
# Claude
# =============================================================================
class ClaudeProvider(BaseProvider):
    name = "claude"

    def __init__(self) -> None:
        if not settings.ANTHROPIC_API_KEY:
            raise LlmError("ANTHROPIC_API_KEY is not set in backend/.env")
        import anthropic

        self._client = anthropic.AsyncAnthropic(
            api_key=settings.ANTHROPIC_API_KEY, timeout=REQUEST_TIMEOUT_SECONDS
        )
        self._model = settings.CLAUDE_MODEL

    def _messages(self, turns: list[ChatTurn]) -> list[dict[str, str]]:
        return [
            {"role": "assistant" if t.role == "assistant" else "user", "content": t.content}
            for t in turns
            if t.content
        ]

    async def complete(
        self, *, system: str, turns: list[ChatTurn], max_tokens: int = 700, temperature: float = 0.3
    ) -> LlmResult:
        try:
            msg = await self._client.messages.create(
                model=self._model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system,
                messages=self._messages(turns),
            )
        except Exception as exc:  # noqa: BLE001
            raise LlmError(f"claude error: {exc}") from exc

        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        tokens = int(msg.usage.input_tokens + msg.usage.output_tokens) if msg.usage else 0
        return LlmResult(text=text.strip(), tokens=tokens, provider=self.name)

    async def stream(
        self, *, system: str, turns: list[ChatTurn], max_tokens: int = 700, temperature: float = 0.3
    ) -> AsyncIterator[str]:
        try:
            async with self._client.messages.stream(
                model=self._model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system,
                messages=self._messages(turns),
            ) as stream:
                async for piece in stream.text_stream:
                    if piece:
                        yield piece
        except Exception as exc:  # noqa: BLE001
            raise LlmError(f"claude stream error: {exc}") from exc


# =============================================================================
# OpenAI
# =============================================================================
class OpenAIProvider(BaseProvider):
    name = "openai"

    def __init__(self) -> None:
        if not settings.OPENAI_API_KEY:
            raise LlmError("OPENAI_API_KEY is not set in backend/.env")
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY, timeout=REQUEST_TIMEOUT_SECONDS)
        self._model = settings.OPENAI_MODEL

    def _messages(self, system: str, turns: list[ChatTurn]) -> list[dict[str, str]]:
        out = [{"role": "system", "content": system}]
        out += [
            {"role": "assistant" if t.role == "assistant" else "user", "content": t.content}
            for t in turns
            if t.content
        ]
        return out

    async def complete(
        self, *, system: str, turns: list[ChatTurn], max_tokens: int = 700, temperature: float = 0.3
    ) -> LlmResult:
        try:
            resp = await self._client.chat.completions.create(
                model=self._model,
                messages=self._messages(system, turns),
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except Exception as exc:  # noqa: BLE001
            raise LlmError(f"openai error: {exc}") from exc
        return LlmResult(
            text=(resp.choices[0].message.content or "").strip(),
            tokens=int(resp.usage.total_tokens) if resp.usage else 0,
            provider=self.name,
        )

    async def stream(
        self, *, system: str, turns: list[ChatTurn], max_tokens: int = 700, temperature: float = 0.3
    ) -> AsyncIterator[str]:
        try:
            stream = await self._client.chat.completions.create(
                model=self._model,
                messages=self._messages(system, turns),
                max_tokens=max_tokens,
                temperature=temperature,
                stream=True,
            )
            async for chunk in stream:
                piece = chunk.choices[0].delta.content if chunk.choices else None
                if piece:
                    yield piece
        except Exception as exc:  # noqa: BLE001
            raise LlmError(f"openai stream error: {exc}") from exc


# =============================================================================
# Factory
# =============================================================================
_provider: BaseProvider | None = None


def get_provider() -> BaseProvider:
    global _provider
    if _provider is None:
        choice = settings.LLM_PROVIDER
        _provider = {
            "gemini": GeminiProvider,
            "claude": ClaudeProvider,
            "openai": OpenAIProvider,
        }[choice]()
        log.info("LLM provider: %s (%s)", choice, getattr(_provider, "_model", "?"))
    return _provider


async def warm_connections() -> None:
    """
    Opens the secure connections to Google BEFORE the visitor's first message.

      Q: Why does that matter?
      A: The first call on a fresh connection pays for the secure handshake —
         measured ~1.8 s for the first reply vs ~0.9 s afterwards. /api/warmup
         runs this when the chat bubble opens, so the visitor never pays it.
         models.get() only reads a model's details: no text generated, no quota.
    """
    try:
        provider = get_provider()
        if isinstance(provider, GeminiProvider):
            await asyncio.wait_for(provider._client.aio.models.get(model=provider._model), 5)
        from app.llm.embeddings import _get_embedder

        embedder = _get_embedder()
        client = getattr(embedder, "_client", None)
        if client is not None and hasattr(client, "aio") and hasattr(client.aio, "models"):
            await asyncio.wait_for(client.aio.models.get(model=embedder._model), 5)
    except Exception as exc:  # noqa: BLE001 — warming is a bonus, never an error
        log.info("connection warm-up skipped: %s", exc)


def reset_provider() -> None:
    """Used by the eval script when it switches providers between runs."""
    global _provider
    _provider = None
