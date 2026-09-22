"""
Every database query in the project lives in this one file.

Why one file: when something is slow or wrong, there is exactly one place to
look, and the API/graph/lead code stays readable because it reads like English
(`await crud.save_message(...)`) instead of SQL.
"""

from __future__ import annotations

import hashlib
import re
from datetime import timedelta
from typing import Any, Sequence

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timezone import ist_today_key, utc_now
from app.db.models import (
    AccessRequest,
    Admin,
    Conversation,
    Lead,
    LlmUsage,
    Message,
    Project,
    ProjectMember,
    ProjectUpdate,
    UnansweredQuestion,
    User,
)


# ------------------------------------------------------------------- small helpers
def hash_ip(ip: str) -> str:
    """We never store a raw IP. A salted hash is enough to spot abuse patterns."""
    return hashlib.sha256(f"praxon::{ip}".encode()).hexdigest()[:32]


def _question_key(question: str) -> str:
    normalised = re.sub(r"[^a-z0-9ऀ-ॿఀ-౿ ]", "", question.lower()).strip()
    normalised = re.sub(r"\s+", " ", normalised)
    return hashlib.sha256(normalised.encode()).hexdigest()[:40]


# -------------------------------------------------------------------- conversations
async def get_or_create_conversation(
    session: AsyncSession, session_id: str, *, ip: str = "", user_agent: str = ""
) -> Conversation:
    row = await session.scalar(select(Conversation).where(Conversation.session_id == session_id))
    if row:
        return row

    row = Conversation(
        session_id=session_id,
        ip_hash=hash_ip(ip) if ip else "",
        user_agent=(user_agent or "")[:300],
        intents=[],
        asked_fields=[],
        skipped_fields=[],
    )
    session.add(row)
    await session.commit()          # no refresh: the id is already filled in by the insert
    return row


async def load_for_chat(
    session: AsyncSession, session_id: str, *, ip: str = "", user_agent: str = ""
) -> tuple[Conversation, Lead | None]:
    """
    The conversation AND its enquiry in ONE database trip. Used on every message.

      Q: Why not get_or_create_conversation() then get_lead()?
      A: That is two trips. From a laptop each trip to Neon in Singapore costs
         ~145 ms, and they happen before the visitor sees a single word. Every
         trip removed from this path is time the visitor stops waiting.
    """
    row = (
        await session.execute(
            select(Conversation, Lead)
            .outerjoin(Lead, Lead.conversation_id == Conversation.id)   # lead may not exist
            .where(Conversation.session_id == session_id)
        )
    ).first()
    if row:
        return row[0], row[1]
    conversation = await get_or_create_conversation(
        session, session_id, ip=ip, user_agent=user_agent
    )
    return conversation, None


async def touch_conversation(
    session: AsyncSession,
    conversation: Conversation,
    *,
    intent: str = "",
    language: str = "",
    commit: bool = True,
) -> None:
    """commit=False: just set the values; the next commit (saving the reply) saves them."""
    conversation.last_active_at = utc_now()
    if intent:
        seen = list(conversation.intents or [])
        if intent not in seen:
            conversation.intents = seen + [intent]
    if language:
        conversation.language = language
    if commit:
        await session.commit()


async def mark_field_asked(session: AsyncSession, conversation: Conversation, field: str) -> None:
    asked = list(conversation.asked_fields or [])
    if field and field not in asked:
        conversation.asked_fields = asked + [field]
        await session.commit()


async def mark_field_skipped(session: AsyncSession, conversation: Conversation, field: str) -> None:
    """Once here, this question is never asked again in this conversation. Ever."""
    skipped = list(conversation.skipped_fields or [])
    if field and field not in skipped:
        conversation.skipped_fields = skipped + [field]
        await session.commit()


async def mark_consent_shown(session: AsyncSession, conversation: Conversation) -> None:
    if not conversation.consent_shown:
        conversation.consent_shown = True
        await session.commit()


# ------------------------------------------------------------------------ messages
async def save_message(
    session: AsyncSession,
    conversation: Conversation,
    *,
    role: str,
    content: str,
    intent: str = "",
    blocked_reason: str = "",
    latency_ms: int = 0,
    total_ms: int = 0,
) -> Message:
    msg = Message(
        conversation_id=conversation.id,
        role=role,
        content=content,
        intent=intent,
        blocked_reason=blocked_reason,
        latency_ms=latency_ms,
        total_ms=total_ms,
    )
    session.add(msg)
    conversation.message_count = (conversation.message_count or 0) + 1
    conversation.last_active_at = utc_now()
    await session.commit()          # no refresh: nothing re-reads the saved message
    return msg


async def recent_messages(
    session: AsyncSession, conversation_id: int, limit: int = 10
) -> list[Message]:
    """Last N messages, oldest first — that is the order the LLM needs them in."""
    rows = (
        await session.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.id.desc())
            .limit(limit)
        )
    ).all()
    return list(reversed(rows))


async def all_messages(session: AsyncSession, conversation_id: int) -> list[Message]:
    rows = await session.scalars(
        select(Message).where(Message.conversation_id == conversation_id).order_by(Message.id)
    )
    return list(rows)


async def count_user_turns(session: AsyncSession, conversation_id: int) -> int:
    return int(
        await session.scalar(
            select(func.count())
            .select_from(Message)
            .where(Message.conversation_id == conversation_id, Message.role == "user")
        )
        or 0
    )


# --------------------------------------------------------------------------- leads
async def get_lead(session: AsyncSession, conversation_id: int) -> Lead | None:
    return await session.scalar(select(Lead).where(Lead.conversation_id == conversation_id))


async def get_or_create_lead(session: AsyncSession, conversation_id: int) -> Lead:
    lead = await get_lead(session, conversation_id)
    if lead:
        return lead
    lead = Lead(conversation_id=conversation_id)
    session.add(lead)
    await session.commit()
    await session.refresh(lead)
    return lead


async def update_lead_fields(
    session: AsyncSession, lead: Lead, fields: dict[str, Any]
) -> tuple[Lead, list[str]]:
    """
    Fills in blanks only.

    Never overwrites something the visitor already told us with something the
    extractor guessed later. Returns the list of field names that actually
    changed, so the caller knows whether an alert is worth sending.
    """
    changed: list[str] = []
    for key, value in fields.items():
        if value in (None, ""):
            continue
        if not hasattr(lead, key):
            continue
        current = getattr(lead, key)
        if current in (None, "", "Details pending") or key in {"timeline_label", "requirement"}:
            if current != value:
                setattr(lead, key, value)
                changed.append(key)
    if changed:
        lead.updated_at = utc_now()
        await session.commit()
        await session.refresh(lead)
    return lead, changed


async def set_extraction_state(session: AsyncSession, lead: Lead, state: str) -> None:
    """
    extraction_attempts counts FAILURES in a row, not extractions.

    It used to count every run, so after a visitor's 3rd answer the retry limit
    was hit and their 4th and 5th messages — name and email — were never read.
    A success now resets it to zero.
    """
    lead.extraction_state = state
    if state == "done":
        lead.extraction_attempts = 0
    else:
        lead.extraction_attempts = (lead.extraction_attempts or 0) + 1
    await session.commit()


async def mark_alert_sent(session: AsyncSession, lead: Lead) -> None:
    lead.alert_sent = True
    await session.commit()


async def pending_extractions(session: AsyncSession, max_attempts: int = 3) -> list[Lead]:
    """
    Issue: "Render may restart the service anytime."

    Anything still marked pending when the app boots is an extraction that was
    interrupted. main.py calls this on startup and finishes the job.
    """
    rows = await session.scalars(
        select(Lead)
        .where(Lead.extraction_state == "pending", Lead.extraction_attempts < max_attempts)
        .order_by(Lead.id.desc())
        .limit(50)
    )
    return list(rows)


# ------------------------------------------------------------ unanswered questions
async def record_unanswered(
    session: AsyncSession, question: str, language: str = "en"
) -> None:
    key = _question_key(question)
    stmt = (
        pg_insert(UnansweredQuestion)
        .values(
            question=question[:2000],
            question_key=key,
            language=language,
            times_asked=1,
            last_asked_at=utc_now(),
        )
        .on_conflict_do_update(
            index_elements=[UnansweredQuestion.question_key],
            set_={
                "times_asked": UnansweredQuestion.times_asked + 1,
                "last_asked_at": utc_now(),
            },
        )
    )
    await session.execute(stmt)
    await session.commit()


# --------------------------------------------------------------------- llm usage
async def increment_llm_usage(session: AsyncSession, *, calls: int = 1, tokens: int = 0) -> int:
    """Atomic upsert. Returns the running call count for today (IST)."""
    day = ist_today_key()
    stmt = (
        pg_insert(LlmUsage)
        .values(day_key=day, calls=calls, tokens=tokens, updated_at=utc_now())
        .on_conflict_do_update(
            index_elements=[LlmUsage.day_key],
            set_={
                "calls": LlmUsage.calls + calls,
                "tokens": LlmUsage.tokens + tokens,
                "updated_at": utc_now(),
            },
        )
        .returning(LlmUsage.calls)
    )
    used = int(await session.scalar(stmt) or 0)
    #   Q: Why commit right here?
    #   A: Until it is committed, today's counter row stays LOCKED. It used to
    #      stay locked for the whole streamed reply (seconds), so a second
    #      visitor's message had to wait for the first visitor's reply to end.
    #      Committing now frees it immediately. Visitors never queue.
    await session.commit()
    return used


async def today_llm_usage(session: AsyncSession) -> dict[str, int]:
    row = await session.get(LlmUsage, ist_today_key())
    return {"calls": row.calls if row else 0, "tokens": row.tokens if row else 0}


# --------------------------------------------------------------------------- admin
async def get_admin(session: AsyncSession, username: str) -> Admin | None:
    return await session.scalar(select(Admin).where(Admin.username == username))


async def create_admin(session: AsyncSession, username: str, password_hash: str) -> Admin:
    admin = Admin(username=username, password_hash=password_hash)
    session.add(admin)
    await session.commit()
    await session.refresh(admin)
    return admin


async def update_admin_password(session: AsyncSession, admin: Admin, password_hash: str) -> None:
    admin.password_hash = password_hash
    await session.commit()


async def record_login(session: AsyncSession, admin: Admin | User) -> None:
    admin.last_login_at = utc_now()
    await session.commit()


# --------------------------------------------------------------------------- users
# Everyone who can log in: owner, team, client. See models.User.

async def find_user_for_login(session: AsyncSession, login: str) -> User | None:
    """Finds by username OR email — "praxon" and "annapu@gmail.com" both work."""
    value = (login or "").strip()
    if not value:
        return None
    return await session.scalar(
        select(User).where(
            (func.lower(User.email) == value.lower()) | (User.username == value)
        )
    )


async def get_user(session: AsyncSession, user_id: int) -> User | None:
    return await session.get(User, user_id)


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    return await session.scalar(select(User).where(func.lower(User.email) == email.strip().lower()))


async def list_users(session: AsyncSession, roles: list[str]) -> Sequence[User]:
    return (
        await session.scalars(select(User).where(User.role.in_(roles)).order_by(User.created_at))
    ).all()


async def create_user(
    session: AsyncSession,
    *,
    role: str,
    email: str = "",
    username: str = "",
    name: str = "",
    company_name: str = "",
    password_hash: str = "",
    created_by_id: int | None = None,
    temporary: bool = False,
) -> User:
    user = User(
        role=role,
        email=email.strip().lower() or None,       # None, not "", so UNIQUE allows many blanks
        username=username.strip() or None,
        name=name.strip(),
        company_name=company_name.strip(),
        password_hash=password_hash,
        created_by_id=created_by_id,
    )
    if temporary:
        mark_temporary_password(user, password_hash)
    session.add(user)
    await session.commit()
    return user


TEMP_PASSWORD_DAYS = 7


def mark_temporary_password(user: User, password_hash: str) -> None:
    """Gives the account a one-time password that must be changed at first sign-in."""
    user.password_hash = password_hash
    user.must_change_password = True
    user.temp_password_expires_at = utc_now() + timedelta(days=TEMP_PASSWORD_DAYS)


async def count_active_owners(session: AsyncSession) -> int:
    return int(
        await session.scalar(
            select(func.count()).select_from(User).where(User.role == "owner", User.is_active.is_(True))
        )
        or 0
    )


# ------------------------------------------------------------------------ projects
async def list_projects(
    session: AsyncSession, *, client_id: int | None = None, member_id: int | None = None
) -> Sequence[Project]:
    """All projects, or only one client's, or only those a team member is assigned to."""
    stmt = select(Project).order_by(Project.updated_at.desc())
    if client_id is not None:
        stmt = stmt.where(Project.client_id == client_id)
    if member_id is not None:
        stmt = stmt.join(ProjectMember, ProjectMember.project_id == Project.id).where(
            ProjectMember.user_id == member_id
        )
    return (await session.scalars(stmt)).all()


async def project_members(session: AsyncSession, project_ids: list[int]) -> dict[int, list[User]]:
    """{project id: [team members on it]} for many projects in one trip."""
    if not project_ids:
        return {}
    rows = await session.execute(
        select(ProjectMember.project_id, User)
        .join(User, User.id == ProjectMember.user_id)
        .where(ProjectMember.project_id.in_(project_ids))
        .order_by(User.name)
    )
    out: dict[int, list[User]] = {pid: [] for pid in project_ids}
    for pid, user in rows:
        out[pid].append(user)
    return out


async def is_project_member(session: AsyncSession, project_id: int, user_id: int) -> bool:
    return bool(
        await session.scalar(
            select(ProjectMember.id).where(
                ProjectMember.project_id == project_id, ProjectMember.user_id == user_id
            )
        )
    )


async def set_project_members(session: AsyncSession, project_id: int, user_ids: list[int]) -> None:
    """Replaces the project's team with exactly these people. Caller commits."""
    await session.execute(delete(ProjectMember).where(ProjectMember.project_id == project_id))
    for uid in dict.fromkeys(user_ids):               # dict.fromkeys = unique, order kept
        session.add(ProjectMember(project_id=project_id, user_id=uid))


# ----------------------------------------------------------------- access requests
async def create_access_request(session: AsyncSession, **fields: str) -> AccessRequest:
    req = AccessRequest(**fields)
    session.add(req)
    await session.commit()
    return req


async def list_access_requests(session: AsyncSession) -> Sequence[AccessRequest]:
    """Pending first, then the 50 most recent handled ones."""
    pending = (
        await session.scalars(
            select(AccessRequest).where(AccessRequest.status == "pending").order_by(AccessRequest.created_at)
        )
    ).all()
    handled = (
        await session.scalars(
            select(AccessRequest)
            .where(AccessRequest.status != "pending")
            .order_by(AccessRequest.handled_at.desc())
            .limit(50)
        )
    ).all()
    return [*pending, *handled]


async def get_access_request(session: AsyncSession, request_id: int) -> AccessRequest | None:
    return await session.get(AccessRequest, request_id)


async def get_project(session: AsyncSession, project_id: int) -> Project | None:
    return await session.get(Project, project_id)


async def project_updates(session: AsyncSession, project_id: int) -> Sequence[ProjectUpdate]:
    return (
        await session.scalars(
            select(ProjectUpdate)
            .where(ProjectUpdate.project_id == project_id)
            .order_by(ProjectUpdate.created_at.desc())      # newest first, like a feed
        )
    ).all()


async def add_project_update(
    session: AsyncSession, project: Project, author: User, *, title: str, body: str
) -> ProjectUpdate:
    update = ProjectUpdate(
        project_id=project.id,
        author_id=author.id,
        author_name=author.name or author.username or author.email or "",
        author_role=author.role,
        title=title.strip()[:200],
        body=body.strip(),
    )
    session.add(update)
    project.updated_at = utc_now()          # the project jumps to the top of lists
    await session.commit()
    return update


# ----------------------------------------------------------------- dashboard reads
async def list_leads(
    session: AsyncSession,
    *,
    status: str = "",
    category: str = "",
    timeline: str = "",
    limit: int = 200,
    offset: int = 0,
) -> Sequence[Lead]:
    stmt = select(Lead).order_by(Lead.created_at.desc()).limit(limit).offset(offset)
    if status:
        stmt = stmt.where(Lead.founder_status == status)
    if category:
        stmt = stmt.where(Lead.category == category)
    if timeline:
        stmt = stmt.where(Lead.timeline_label == timeline)
    return (await session.scalars(stmt)).all()


async def get_lead_by_id(session: AsyncSession, lead_id: int) -> Lead | None:
    return await session.get(Lead, lead_id)


async def set_founder_status(
    session: AsyncSession, lead_id: int, status: str, notes: str | None = None
) -> Lead | None:
    lead = await session.get(Lead, lead_id)
    if not lead:
        return None
    lead.founder_status = status
    if notes is not None:
        lead.founder_notes = notes
    lead.updated_at = utc_now()
    await session.commit()
    await session.refresh(lead)
    return lead


async def delete_lead(session: AsyncSession, lead_id: int, *, wipe_conversation: bool = True) -> bool:
    """
    Privacy deletion (DPDP: "allow deletion").

    Deleting the conversation too is the default, because the chat transcript
    contains the same personal details the lead row does — deleting only the
    row would be theatre.
    """
    lead = await session.get(Lead, lead_id)
    if not lead:
        return False
    conv_id = lead.conversation_id
    await session.execute(delete(Lead).where(Lead.id == lead_id))
    if wipe_conversation:
        await session.execute(delete(Conversation).where(Conversation.id == conv_id))
    await session.commit()
    return True


async def list_conversations(
    session: AsyncSession, *, limit: int = 100, offset: int = 0, only_with_leads: bool = False
) -> Sequence[Conversation]:
    stmt = (
        select(Conversation)
        .order_by(Conversation.last_active_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if only_with_leads:
        stmt = stmt.join(Lead, Lead.conversation_id == Conversation.id)
    return (await session.scalars(stmt)).all()


async def get_conversation_by_id(session: AsyncSession, conv_id: int) -> Conversation | None:
    return await session.get(Conversation, conv_id)


async def list_unanswered(
    session: AsyncSession, *, limit: int = 100, include_resolved: bool = False
) -> Sequence[UnansweredQuestion]:
    stmt = (
        select(UnansweredQuestion)
        .order_by(UnansweredQuestion.times_asked.desc(), UnansweredQuestion.last_asked_at.desc())
        .limit(limit)
    )
    if not include_resolved:
        stmt = stmt.where(UnansweredQuestion.resolved.is_(False))
    return (await session.scalars(stmt)).all()


async def resolve_unanswered(session: AsyncSession, item_id: int) -> bool:
    row = await session.get(UnansweredQuestion, item_id)
    if not row:
        return False
    row.resolved = True
    await session.commit()
    return True


async def dashboard_stats(session: AsyncSession) -> dict[str, Any]:
    week_ago = utc_now() - timedelta(days=7)

    total_conversations = int(
        await session.scalar(select(func.count()).select_from(Conversation)) or 0
    )
    total_leads = int(await session.scalar(select(func.count()).select_from(Lead)) or 0)
    leads_with_contact = int(
        await session.scalar(
            select(func.count()).select_from(Lead).where((Lead.email != "") | (Lead.phone != ""))
        )
        or 0
    )
    conversations_7d = int(
        await session.scalar(
            select(func.count()).select_from(Conversation).where(Conversation.started_at >= week_ago)
        )
        or 0
    )
    leads_7d = int(
        await session.scalar(
            select(func.count()).select_from(Lead).where(Lead.created_at >= week_ago)
        )
        or 0
    )

    by_timeline = {
        row[0]: row[1]
        for row in (
            await session.execute(
                select(Lead.timeline_label, func.count()).group_by(Lead.timeline_label)
            )
        ).all()
    }
    by_status = {
        row[0]: row[1]
        for row in (
            await session.execute(
                select(Lead.founder_status, func.count()).group_by(Lead.founder_status)
            )
        ).all()
    }
    by_category = {
        row[0]: row[1]
        for row in (
            await session.execute(select(Lead.category, func.count()).group_by(Lead.category))
        ).all()
    }

    top_questions = [
        {"question": r[0], "count": r[1]}
        for r in (
            await session.execute(
                select(Message.content, func.count())
                .where(Message.role == "user", func.length(Message.content) < 160)
                .group_by(Message.content)
                .order_by(func.count().desc())
                .limit(10)
            )
        ).all()
    ]

    unanswered_count = int(
        await session.scalar(
            select(func.count())
            .select_from(UnansweredQuestion)
            .where(UnansweredQuestion.resolved.is_(False))
        )
        or 0
    )

    avg_first_word_ms = float(
        await session.scalar(
            select(func.avg(Message.latency_ms)).where(
                Message.role == "assistant", Message.latency_ms > 0
            )
        )
        or 0
    )

    return {
        "total_conversations": total_conversations,
        "total_leads": total_leads,
        "leads_with_contact": leads_with_contact,
        "conversations_7d": conversations_7d,
        "leads_7d": leads_7d,
        "by_timeline": by_timeline,
        "by_status": by_status,
        "by_category": by_category,
        "top_questions": top_questions,
        "unanswered_count": unanswered_count,
        "avg_first_word_ms": round(avg_first_word_ms),
        "llm_today": await today_llm_usage(session),
    }


# -------------------------------------------------------------------- maintenance
async def ensure_schema(session: AsyncSession) -> None:
    """
    Creates the pgvector extension and the index that makes search fast.

    Run from scripts/ingest.py, not on every boot — Render restarts often and
    this does not need to run every time.
    """
    await session.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    await session.commit()


async def ensure_vector_index(session: AsyncSession) -> None:
    await session.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_documents_embedding "
            "ON documents USING hnsw (embedding vector_cosine_ops)"
        )
    )
    await session.commit()
