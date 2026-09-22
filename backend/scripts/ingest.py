"""
Load client/content into Neon. Run this from your laptop, never automatically.

    python backend/scripts/ingest.py               # normal run
    python backend/scripts/ingest.py --force       # re-embed everything
    python backend/scripts/ingest.py --check       # test retrieval, change nothing

Why it is manual: ingesting costs embedding API calls and changes what the bot
knows. That should happen when YOU edit the content, not on every Render restart.

Why it is safe to run repeatedly (the "DB must stay stable across re-runs" rule):
  * chunks are matched on (source, chunk_index) and UPDATED in place
  * unchanged chunks are skipped entirely — no API call, no write
  * only content you actually deleted is removed
  * conversations, leads and admins are never touched

Point it at the dev branch while testing (DATABASE_URL in backend/.env), and at
the production branch when you want the live site to see new content.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Make `app.*` importable when running this file directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from app.config import settings  # noqa: E402
from app.core.logging import get_logger, setup_logging  # noqa: E402
from app.db import crud  # noqa: E402
from app.db.database import dispose_engine, get_engine, run, session_scope  # noqa: E402
from app.db.models import Base  # noqa: E402
from app.llm.embeddings import embed_documents  # noqa: E402
from app.rag.loader import load_chunks  # noqa: E402
from app.rag.retriever import retrieve  # noqa: E402
from app.rag.vectorstore import (  # noqa: E402
    count_documents,
    delete_orphans,
    existing_hashes,
    upsert_chunks,
)

setup_logging()
log = get_logger("ingest")

# These run at the end of a normal ingest as a smoke test. Two of them are
# deliberately Telugu and Hindi: issue #7 says multilingual retrieval must be
# tested, not assumed.
SMOKE_TESTS = [
    ("en", "What services do you offer?"),
    ("en", "How much does a website cost?"),
    ("en", "Do you sign an NDA?"),
    ("en", "Are you hiring interns?"),
    ("te", "మీరు వెబ్‌సైట్ ఎంత ధరకు చేస్తారు?"),          # "how much for a website?"
    ("hi", "क्या आप मोबाइल ऐप बनाते हैं?"),                  # "do you make mobile apps?"
    ("mixed", "website cost entha?"),                        # Tenglish
    ("mixed", "app banane ka kitna charge hai?"),            # Hinglish
]


async def create_tables() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        # pgvector must exist before a vector column can be created.
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
    log.info("schema ready (extension + tables)")


async def run_ingest(force: bool = False) -> None:
    log.info("content folder: %s", settings.content_path)
    chunks = load_chunks()
    if not chunks:
        log.error("no chunks produced — nothing to ingest")
        return

    session = await session_scope()
    try:
        await crud.ensure_schema(session)

        known = {} if force else await existing_hashes(session)
        todo = [
            c for c in chunks
            if force or known.get((c.source, c.chunk_index)) != c.content_hash
        ]

        skipped = len(chunks) - len(todo)
        if skipped:
            log.info("%d chunks unchanged — skipping (no embedding cost)", skipped)

        if todo:
            log.info("embedding %d chunks...", len(todo))
            vectors = await embed_documents([c.embed_text for c in todo])
            await upsert_chunks(session, todo, vectors)
        else:
            log.info("nothing to embed — content has not changed")

        removed = await delete_orphans(session, chunks)
        await crud.ensure_vector_index(session)

        total = await count_documents(session)
        log.info("-" * 58)
        log.info("  embedded/updated : %d", len(todo))
        log.info("  unchanged        : %d", skipped)
        log.info("  removed          : %d", removed)
        log.info("  total in database: %d", total)
        log.info("-" * 58)
    finally:
        await session.close()


async def run_checks() -> None:
    session = await session_scope()
    try:
        total = await count_documents(session)
        if total == 0:
            log.error("database has no documents — run ingest first")
            return

        log.info("retrieval smoke test against %d chunks", total)
        log.info("")
        failures = 0
        for lang, question in SMOKE_TESTS:
            result = await retrieve(session, question)
            status = "OK  " if result.found else "MISS"
            if not result.found:
                failures += 1
            top = result.hits[0] if result.hits else None
            log.info(
                "  [%s] %-4s %-46s -> %s (%.2f)",
                lang,
                status,
                question[:46],
                f"{top.source} / {top.title[:28]}" if top else "nothing above threshold",
                result.best_score,
            )

        log.info("")
        if failures:
            log.warning(
                "%d/%d questions found nothing. If the Telugu/Hindi ones failed, check "
                "GEMINI_EMBED_MODEL, then try lowering limits.retrieval_min_score in "
                "client/company.yaml.",
                failures,
                len(SMOKE_TESTS),
            )
        else:
            log.info("all smoke tests retrieved content, including Telugu and Hindi.")
    finally:
        await session.close()


async def main() -> None:
    parser = argparse.ArgumentParser(description="Load client content into Neon + pgvector")
    parser.add_argument("--force", action="store_true", help="re-embed everything")
    parser.add_argument("--check", action="store_true", help="only run retrieval tests")
    args = parser.parse_args()

    masked = settings.DATABASE_URL.split("@")[-1][:60] if settings.DATABASE_URL else "(not set)"
    log.info("database: ...@%s", masked)

    try:
        if args.check:
            await run_checks()
        else:
            await create_tables()
            await run_ingest(force=args.force)
            await run_checks()
    finally:
        await dispose_engine()


if __name__ == "__main__":
    run(main())     # not asyncio.run — see run() in app/db/database.py
