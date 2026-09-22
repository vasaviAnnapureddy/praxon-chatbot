"""
Question in, grounded context out.

This is where issue #1 (hallucination) is actually stopped. The prompt tells the
model to use only what it is given; this file decides what it is given, and —
more importantly — decides when to give it NOTHING and trigger the honest
"I don't know" path instead.

The min-score threshold is the whole trick. Without it, the nearest chunk is
always returned, however unrelated, and the model dutifully writes an answer out
of irrelevant text. With it, a question about cricket scores retrieves nothing,
and the assistant says so and offers contact options.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_company
from app.core.logging import get_logger
from app.llm.embeddings import embed_query
from app.rag.vectorstore import Hit, search

log = get_logger("rag.retriever")


@dataclass
class Retrieval:
    hits: list[Hit]
    context: str
    found: bool
    best_score: float
    took_ms: int

    @property
    def sources(self) -> list[str]:
        seen: list[str] = []
        for h in self.hits:
            if h.source not in seen:
                seen.append(h.source)
        return seen


def _format_context(hits: list[Hit]) -> str:
    blocks: list[str] = []
    for i, hit in enumerate(hits, start=1):
        label = f"{hit.source}" + (f" — {hit.title}" if hit.title else "")
        blocks.append(f"[{i}] ({label})\n{hit.content}")
    return "\n\n".join(blocks)


async def retrieve(
    session: AsyncSession,
    question: str,
    *,
    top_k: int | None = None,
    min_score: float | None = None,
    vector: list[float] | None = None,
) -> Retrieval:
    """vector: pass it in if it was already worked out (chat.py starts that early)."""
    company = get_company()
    k = top_k or int(company.get("limits.retrieval_top_k", 4))
    floor = min_score if min_score is not None else float(company.get("limits.retrieval_min_score", 0.28))

    t0 = time.perf_counter()
    if vector is None:
        vector = await embed_query(question)
    hits = await search(session, vector, top_k=k)
    took = int((time.perf_counter() - t0) * 1000)

    best = hits[0].score if hits else 0.0
    good = [h for h in hits if h.score >= floor]

    log.info(
        "retrieve %-40s best=%.3f kept=%d/%d %dms",
        question[:40].replace("\n", " "),
        best,
        len(good),
        len(hits),
        took,
    )

    return Retrieval(
        hits=good,
        context=_format_context(good),
        found=bool(good),
        best_score=best,
        took_ms=took,
    )
