"""
Reads and writes the `documents` table — the pgvector side of things.

Two design notes:

1. Cosine distance (`<=>`), not L2. Embeddings are direction, not magnitude;
   cosine is what the model was trained for. Similarity = 1 - distance, so a
   score of 1.0 is identical and 0.0 is unrelated.

2. `ON CONFLICT ... DO UPDATE` on (source, chunk_index).
   Re-running ingest.py after editing content updates rows in place. Rows that
   did not change keep the same id. This is the "DB must stay stable across
   re-runs" rule — you never get duplicate knowledge or a wiped table.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.logging import get_logger
from app.db.models import VectorType
from app.rag.loader import Chunk

log = get_logger("rag.store")


@dataclass
class Hit:
    source: str
    title: str
    content: str
    score: float  # 1.0 = perfect match, 0.0 = unrelated


async def upsert_chunks(
    session: AsyncSession, chunks: list[Chunk], vectors: list[list[float]]
) -> int:
    if len(chunks) != len(vectors):
        raise ValueError("chunks and vectors must be the same length")

    stmt = text(
        """
        INSERT INTO documents
            (source, title, chunk_index, content, content_hash, embedding, created_at)
        VALUES
            (:source, :title, :chunk_index, :content, :content_hash, :embedding, NOW())
        ON CONFLICT (source, chunk_index) DO UPDATE SET
            title        = EXCLUDED.title,
            content      = EXCLUDED.content,
            content_hash = EXCLUDED.content_hash,
            embedding    = EXCLUDED.embedding
        """
    ).bindparams(bindparam("embedding", type_=VectorType(settings.EMBED_DIM)))

    written = 0
    for chunk, vector in zip(chunks, vectors, strict=True):
        await session.execute(
            stmt,
            {
                "source": chunk.source,
                "title": chunk.title,
                "chunk_index": chunk.chunk_index,
                "content": chunk.content,
                "content_hash": chunk.content_hash,
                "embedding": vector,
            },
        )
        written += 1
    await session.commit()
    log.info("upserted %d chunks", written)
    return written


async def existing_hashes(session: AsyncSession) -> dict[tuple[str, int], str]:
    """Used by ingest.py to skip re-embedding chunks that have not changed."""
    rows = await session.execute(text("SELECT source, chunk_index, content_hash FROM documents"))
    return {(r[0], r[1]): r[2] for r in rows.all()}


async def delete_orphans(session: AsyncSession, chunks: list[Chunk]) -> int:
    """
    Removes rows for content that no longer exists.

    Without this, deleting a paragraph from services.md would leave the old
    version in the database, and the assistant would keep quoting text the
    founder deliberately removed.
    """
    keep = {(c.source, c.chunk_index) for c in chunks}
    rows = await session.execute(text("SELECT id, source, chunk_index FROM documents"))
    orphan_ids = [r[0] for r in rows.all() if (r[1], r[2]) not in keep]
    if not orphan_ids:
        return 0
    await session.execute(
        text("DELETE FROM documents WHERE id = ANY(:ids)"), {"ids": orphan_ids}
    )
    await session.commit()
    log.info("deleted %d orphan chunks", len(orphan_ids))
    return len(orphan_ids)


async def search(
    session: AsyncSession, query_vector: list[float], *, top_k: int = 4
) -> list[Hit]:
    stmt = text(
        """
        SELECT source, title, content, 1 - (embedding <=> :qv) AS score
        FROM documents
        ORDER BY embedding <=> :qv
        LIMIT :k
        """
    ).bindparams(bindparam("qv", type_=VectorType(settings.EMBED_DIM)))

    rows = await session.execute(stmt, {"qv": query_vector, "k": top_k})
    return [Hit(source=r[0], title=r[1], content=r[2], score=float(r[3])) for r in rows.all()]


async def count_documents(session: AsyncSession) -> int:
    return int(await session.scalar(text("SELECT COUNT(*) FROM documents")) or 0)
