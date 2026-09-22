"""
Reads client/content/*.md (and .pdf) and cuts it into chunks worth embedding.

Chunking strategy: split on markdown headings first, then split anything still
too long on blank lines. Heading-aware chunking matters here because the content
is written as questions and sections — "Do you sign an NDA?" and its answer stay
in one chunk, which is exactly what we want retrieval to return.

Each chunk carries its source file and nearest heading, so the assistant can say
where an answer came from and the dashboard can show it.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from app.config import settings
from app.core.logging import get_logger

log = get_logger("rag.loader")

MAX_CHARS = 1100     # ~250 tokens: big enough for a full answer, small enough to be precise
MIN_CHARS = 80       # anything shorter is a stray heading, not content
OVERLAP_CHARS = 120  # keeps a sentence that straddles a boundary findable


@dataclass
class Chunk:
    source: str
    title: str
    chunk_index: int
    content: str

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(f"{self.source}|{self.content}".encode()).hexdigest()[:64]

    @property
    def embed_text(self) -> str:
        """
        What actually gets embedded.

        Prefixing the source and heading gives the embedding real context — a
        bare "2 to 4 weeks" row is meaningless on its own, but
        "process.md > Timelines, realistically: 2 to 4 weeks" is findable.
        """
        head = f"{self.source.replace('.md', '')} > {self.title}".strip(" >")
        return f"{head}\n{self.content}" if head else self.content


def _read_markdown(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _read_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:  # pragma: no cover
        log.warning("pypdf not installed — skipping %s", path.name)
        return ""
    reader = PdfReader(str(path))
    return "\n\n".join((page.extract_text() or "") for page in reader.pages)


def _split_by_heading(text: str) -> list[tuple[str, str]]:
    """Returns [(heading, body)] — everything before the first heading gets ''."""
    lines = text.splitlines()
    sections: list[tuple[str, list[str]]] = [("", [])]
    for line in lines:
        m = re.match(r"^(#{1,6})\s+(.*)$", line.strip())
        if m:
            sections.append((m.group(2).strip(), []))
        else:
            sections[-1][1].append(line)
    return [(h, "\n".join(b).strip()) for h, b in sections if "\n".join(b).strip()]


def _split_long(body: str) -> list[str]:
    if len(body) <= MAX_CHARS:
        return [body]

    parts: list[str] = []
    buffer = ""
    for para in re.split(r"\n\s*\n", body):
        para = para.strip()
        if not para:
            continue
        if len(buffer) + len(para) + 2 <= MAX_CHARS:
            buffer = f"{buffer}\n\n{para}" if buffer else para
            continue
        if buffer:
            parts.append(buffer)
            tail = buffer[-OVERLAP_CHARS:]
            buffer = f"{tail}\n\n{para}" if len(para) < MAX_CHARS else para
        else:
            # One monster paragraph: hard-cut it.
            for i in range(0, len(para), MAX_CHARS):
                parts.append(para[i : i + MAX_CHARS])
            buffer = ""
    if buffer:
        parts.append(buffer)
    return parts


def load_chunks(content_dir: Path | None = None) -> list[Chunk]:
    directory = content_dir or settings.content_path
    if not directory.exists():
        raise FileNotFoundError(f"Content folder not found: {directory}")

    files = sorted(
        [p for p in directory.iterdir() if p.suffix.lower() in {".md", ".markdown", ".pdf", ".txt"}]
    )
    if not files:
        raise FileNotFoundError(f"No .md/.pdf files in {directory}")

    chunks: list[Chunk] = []
    for path in files:
        raw = _read_pdf(path) if path.suffix.lower() == ".pdf" else _read_markdown(path)
        if not raw.strip():
            log.warning("empty file skipped: %s", path.name)
            continue

        # The "> PLACEHOLDER" and "> RULE FOR THE ASSISTANT" blockquotes are
        # instructions to us, not facts about the company. Strip them so they
        # never get retrieved and quoted back at a visitor.
        raw = re.sub(r"^>.*$", "", raw, flags=re.MULTILINE)

        index = 0
        for heading, body in _split_by_heading(raw):
            for piece in _split_long(body):
                piece = piece.strip()
                if len(piece) < MIN_CHARS:
                    continue
                chunks.append(
                    Chunk(source=path.name, title=heading[:280], chunk_index=index, content=piece)
                )
                index += 1
        log.info("%-14s -> %2d chunks", path.name, index)

    log.info("total chunks: %d from %d files", len(chunks), len(files))
    return chunks
