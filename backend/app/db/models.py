"""
Every table in the project. Six of them plus a usage counter.

A note on the vector column: we use the pgvector EXTENSION in Postgres, but not
the `pgvector` PYTHON package — that package pulls in numpy, and numpy costs
~40 MB of RAM we do not have on Render's free box for no benefit. A vector in
Postgres is just text on the wire (`[0.12,-0.04,...]`), so the 25-line
`VectorType` below does the whole job with zero dependencies.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import UserDefinedType

from app.config import settings
from app.core.timezone import utc_now


class Base(DeclarativeBase):
    pass


class VectorType(UserDefinedType):
    """Minimal bridge between a Python list[float] and Postgres `vector`."""

    cache_ok = True

    def __init__(self, dim: int) -> None:
        self.dim = dim

    def get_col_spec(self, **kw: Any) -> str:  # noqa: ANN401
        return f"vector({self.dim})"

    def bind_processor(self, dialect):  # noqa: ANN001, ANN201
        def process(value):  # noqa: ANN001, ANN202
            if value is None:
                return None
            return "[" + ",".join(f"{float(v):.7g}" for v in value) + "]"

        return process

    def result_processor(self, dialect, coltype):  # noqa: ANN001, ANN201
        def process(value):  # noqa: ANN001, ANN202
            if value is None:
                return None
            if isinstance(value, (list, tuple)):
                return list(value)
            return [float(x) for x in str(value).strip("[]").split(",") if x]

        return process


def _now() -> datetime:
    return utc_now()


# ---------------------------------------------------------------- knowledge base
class Document(Base):
    """One chunk of client content, with its embedding and where it came from."""

    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(200), index=True)       # "services.md"
    title: Mapped[str] = mapped_column(String(300), default="")        # nearest heading
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    content: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)  # skip re-embedding
    embedding: Mapped[list[float]] = mapped_column(VectorType(settings.EMBED_DIM))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    __table_args__ = (UniqueConstraint("source", "chunk_index", name="uq_doc_source_chunk"),)


# ------------------------------------------------------------------ conversations
class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    last_active_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    language: Mapped[str] = mapped_column(String(16), default="en")    # en/te/hi/mixed
    intents: Mapped[list] = mapped_column(JSONB, default=list)         # every intent seen
    ip_hash: Mapped[str] = mapped_column(String(64), default="")       # hashed, never raw
    user_agent: Mapped[str] = mapped_column(String(300), default="")

    # --- lead-question bookkeeping (feature c) -----------------------------
    # asked: we have put this question to them once. Never ask twice.
    # skipped: they ignored or refused it. Never ask again, ever.
    asked_fields: Mapped[list] = mapped_column(JSONB, default=list)
    skipped_fields: Mapped[list] = mapped_column(JSONB, default=list)
    consent_shown: Mapped[bool] = mapped_column(Boolean, default=False)

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", order_by="Message.id"
    )
    lead: Mapped["Lead | None"] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", uselist=False
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))                      # user | assistant
    content: Mapped[str] = mapped_column(Text)
    intent: Mapped[str] = mapped_column(String(32), default="")
    blocked_reason: Mapped[str] = mapped_column(String(48), default="")
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)        # time to FIRST word
    total_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")

    __table_args__ = (Index("ix_messages_conv_created", "conversation_id", "created_at"),)


# --------------------------------------------------------------------------- leads
class Lead(Base):
    """
    What the visitor told us. Facts only.

    There is deliberately NO score, rating, grade or priority column. The bot
    states what was said and attaches a factual timeline label; the founder
    decides who is worth a call.
    """

    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), unique=True, index=True
    )

    requirement: Mapped[str] = mapped_column(Text, default="")
    budget: Mapped[str] = mapped_column(String(80), default="")
    timeline_raw: Mapped[str] = mapped_column(String(120), default="")
    timeline_label: Mapped[str] = mapped_column(String(48), default="Details pending")

    name: Mapped[str] = mapped_column(String(120), default="")
    company_name: Mapped[str] = mapped_column(String(160), default="")
    email: Mapped[str] = mapped_column(String(200), default="", index=True)
    phone: Mapped[str] = mapped_column(String(32), default="")

    category: Mapped[str] = mapped_column(String(24), default="enquiry")  # enquiry | careers
    founder_status: Mapped[str] = mapped_column(String(24), default="New")
    founder_notes: Mapped[str] = mapped_column(Text, default="")

    alert_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    # pending -> done | failed. Anything left "pending" is retried on startup,
    # which is how a mid-extraction Render restart cannot lose a lead.
    extraction_state: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    extraction_attempts: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    conversation: Mapped[Conversation] = relationship(back_populates="lead")

    @property
    def has_contact(self) -> bool:
        return bool(self.email or self.phone)


# ------------------------------------------------------------- unanswered questions
class UnansweredQuestion(Base):
    """
    Feature (a): when retrieval finds nothing good, the question is filed here.

    This list is the single most useful thing the founder gets out of the
    dashboard — it is literally a to-do list of content the website is missing.
    """

    __tablename__ = "unanswered_questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    question: Mapped[str] = mapped_column(Text)
    question_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    times_asked: Mapped[int] = mapped_column(Integer, default=1)
    language: Mapped[str] = mapped_column(String(16), default="en")
    last_asked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)


# -------------------------------------------------------------------------- admin
class Admin(Base):
    __tablename__ = "admins"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# =============================================================================
# People who can LOG IN — team and customers. (Visitors never log in.)
# =============================================================================
class User(Base):
    """
    One row per person with a login. The `role` decides everything they can see:

        owner  -> everything, and manages the team        (you)
        team   -> dashboard, enquiries, clients, projects  (Praxon staff)
        client -> ONLY their own projects, in the portal   (Praxon's customers)

      Q: Why one table with a role, not separate tables for team and clients?
      A: One login system to secure instead of two. The role is checked on
         every request, so a client token is simply refused by team pages.

      Q: How can someone log in with Google if they have no password?
      A: password_hash stays "" for them. Google proves who they are; we only
         check their email is in this table and active. Nobody can sign
         themselves up — somebody on the team must add their email first.

    The old `admins` table is kept untouched; scripts/upgrade_db.py copies it
    into here once, as the owner.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str | None] = mapped_column(String(200), unique=True, index=True, nullable=True)
    username: Mapped[str | None] = mapped_column(String(64), unique=True, index=True, nullable=True)
    name: Mapped[str] = mapped_column(String(120), default="")
    company_name: Mapped[str] = mapped_column(String(160), default="")    # clients
    role: Mapped[str] = mapped_column(String(16), index=True)             # owner | team | client
    password_hash: Mapped[str] = mapped_column(String(255), default="")   # "" = Google only
    google_sub: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Temporary password: True until the person picks their own on first sign-in.
    #   Q: Why an expiry date too?
    #   A: If the WhatsApp message with the temporary password is lost or seen
    #      by someone else, it stops working by itself after 7 days.
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    temp_password_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    projects: Mapped[list["Project"]] = relationship(
        back_populates="client", cascade="all, delete-orphan", order_by="Project.id"
    )


class Project(Base):
    """A client's project, as the CLIENT sees it in the portal."""

    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str] = mapped_column(Text, default="")
    stage: Mapped[str] = mapped_column(String(48), default="Discovery call")
    progress: Mapped[int] = mapped_column(Integer, default=0)            # 0-100
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    client: Mapped[User] = relationship(back_populates="projects")
    updates: Mapped[list["ProjectUpdate"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="ProjectUpdate.id"
    )


class ProjectUpdate(Base):
    """One entry in a project's timeline — a team update, or a client's reply."""

    __tablename__ = "project_updates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # Name and role copied at the time of writing, so the timeline still reads
    # correctly even if that person's account is later removed.
    author_name: Mapped[str] = mapped_column(String(120), default="")
    author_role: Mapped[str] = mapped_column(String(16), default="team")
    title: Mapped[str] = mapped_column(String(200), default="")
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    project: Mapped[Project] = relationship(back_populates="updates")


class ProjectMember(Base):
    """Which team members work on which project. A team member sees ONLY these."""

    #   Q: Why a separate table, not an "assigned_to" column on projects?
    #   A: One column holds one person. A project can have a designer AND a
    #      developer — one row each here.
    __tablename__ = "project_members"
    __table_args__ = (UniqueConstraint("project_id", "user_id", name="uq_project_member"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AccessRequest(Base):
    """A would-be client asking for a login from the "Request access" link."""

    #   Q: Why store a request instead of making the account straight away?
    #   A: No sign-ups. A person on the team reads it and decides — approve
    #      makes the account, reject closes it. Nobody gets in by themselves.
    __tablename__ = "access_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(200), index=True)
    company_name: Mapped[str] = mapped_column(String(160), default="")
    message: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)  # pending|approved|rejected
    handled_by_name: Mapped[str] = mapped_column(String(120), default="")
    handled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class LlmUsage(Base):
    """One row per IST day. The daily cap counts against this."""

    __tablename__ = "llm_usage"

    day_key: Mapped[str] = mapped_column(String(10), primary_key=True)  # "2026-09-18"
    calls: Mapped[int] = mapped_column(Integer, default=0)
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
