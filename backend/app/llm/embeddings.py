"""
Text -> vector.

Issue #7 (multilingual retrieval) is solved right here, not in the retriever.
Gemini's embedding models are trained across languages, so the Telugu sentence
"మీ ధర ఎంత?" lands near the English text about pricing. That is why a Telugu
question can find an English answer without translating anything.

Embeddings always use Gemini, even when LLM_PROVIDER is claude — Anthropic has
no embeddings API, and mixing embedding models inside one database is not
possible anyway (vectors from two different models are not comparable).
OpenAI is supported as an alternative for anyone with no Gemini key.

IMPORTANT: EMBED_DIM must match the model and must never change after content
has been ingested. The database column is a fixed width. If you change the
model, re-ingest everything.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict

from app.config import settings
from app.core.logging import get_logger

log = get_logger("embeddings")

# Gemini's embedding API takes a task hint. Using the right one on each side
# measurably improves retrieval: documents are embedded as documents, questions
# as questions.
TASK_DOCUMENT = "RETRIEVAL_DOCUMENT"
TASK_QUERY = "RETRIEVAL_QUERY"

_BATCH = 32


class EmbeddingError(RuntimeError):
    pass


class _GeminiEmbedder:
    def __init__(self) -> None:
        from google import genai

        self._client = genai.Client(api_key=settings.GEMINI_API_KEY)
        self._model = settings.GEMINI_EMBED_MODEL

    async def embed(self, texts: list[str], task: str) -> list[list[float]]:
        from google.genai import types

        out: list[list[float]] = []
        for i in range(0, len(texts), _BATCH):
            batch = texts[i : i + _BATCH]
            try:
                resp = await asyncio.wait_for(
                    self._client.aio.models.embed_content(
                        model=self._model,
                        contents=batch,
                        # output_dimensionality: gemini-embedding-001 returns 3072
                        # numbers by default, but our database column holds 768.
                        # Without this, ingest fails with a size mismatch.
                        # (No normalising needed: cosine distance ignores length.)
                        config=types.EmbedContentConfig(
                            task_type=task,
                            output_dimensionality=settings.EMBED_DIM,
                        ),
                    ),
                    timeout=30,
                )
            except Exception as exc:  # noqa: BLE001
                raise EmbeddingError(f"gemini embedding failed: {exc}") from exc
            out.extend([list(e.values) for e in resp.embeddings])
        return out


class _OpenAIEmbedder:
    def __init__(self) -> None:
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        self._model = "text-embedding-3-small"

    async def embed(self, texts: list[str], task: str) -> list[list[float]]:
        try:
            resp = await self._client.embeddings.create(
                model=self._model, input=texts, dimensions=settings.EMBED_DIM
            )
        except Exception as exc:  # noqa: BLE001
            raise EmbeddingError(f"openai embedding failed: {exc}") from exc
        return [list(d.embedding) for d in resp.data]


_embedder = None


def _get_embedder():  # noqa: ANN202
    global _embedder
    if _embedder is None:
        if settings.GEMINI_API_KEY:
            _embedder = _GeminiEmbedder()
            log.info("embeddings: gemini %s (dim %s)", settings.GEMINI_EMBED_MODEL, settings.EMBED_DIM)
        elif settings.OPENAI_API_KEY:
            _embedder = _OpenAIEmbedder()
            log.info("embeddings: openai text-embedding-3-small (dim %s)", settings.EMBED_DIM)
        else:
            raise EmbeddingError(
                "No embedding key. Set GEMINI_API_KEY (recommended) or OPENAI_API_KEY."
            )
    return _embedder


async def embed_documents(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    vectors = await _get_embedder().embed(texts, TASK_DOCUMENT)
    _check_dim(vectors)
    return vectors


# Questions already turned into numbers, newest last. Holds 512 — a few MB.
_query_cache: "OrderedDict[str, list[float]]" = OrderedDict()
_QUERY_CACHE_SIZE = 512


async def embed_query(text: str) -> list[float]:
    """
    Question -> numbers, remembering questions it has already seen.

      Q: Why remember them?
      A: Each call is ~480 ms at Google, before the reply can start. Visitors
         ask the same things constantly ("Do you sign an NDA?"), and the same
         text always gives the same numbers — so a repeat skips Google entirely.
         Cleared on restart, which is fine: it refills in minutes.
    """
    key = " ".join(text.lower().split())          # "Do you  sign an NDA?" == "do you sign an nda?"
    cached = _query_cache.get(key)
    if cached is not None:
        _query_cache.move_to_end(key)             # recently used -> keep it longer
        return cached

    vectors = await _get_embedder().embed([text], TASK_QUERY)
    _check_dim(vectors)
    _query_cache[key] = vectors[0]
    if len(_query_cache) > _QUERY_CACHE_SIZE:
        _query_cache.popitem(last=False)          # forget the least recently used
    return vectors[0]


def _check_dim(vectors: list[list[float]]) -> None:
    if vectors and len(vectors[0]) != settings.EMBED_DIM:
        raise EmbeddingError(
            f"Embedding model returned {len(vectors[0])} numbers but EMBED_DIM is "
            f"{settings.EMBED_DIM}. Fix EMBED_DIM in backend/.env, drop the documents "
            f"table, and re-run ingest.py."
        )
