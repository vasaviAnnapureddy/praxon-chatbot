"""
The team's side of accounts, projects and access requests. All under /api/admin.

    TEAM (owner adds)          GET/POST  /api/admin/team
    CLIENTS (owner or team)    GET/POST  /api/admin/clients
    ANY ACCOUNT                PATCH     /api/admin/users/{id}   (switch off, rename, new temporary password)
    PROJECTS                   GET/POST  /api/admin/projects
                               GET/PATCH/DELETE /api/admin/projects/{id}
    PROJECT UPDATES            POST      /api/admin/projects/{id}/updates
    ACCESS REQUESTS            GET       /api/admin/requests
                               POST      /api/admin/requests/{id}/approve | /reject

Who may do what:
    owner -> everything: adds team members, sees every project, assigns people
    team  -> adds clients; sees and edits ONLY the projects they are assigned to
    (clients never reach this file — require_team refuses them)

Nobody types a password for someone else. Adding a person (or resetting their
password) makes a TEMPORARY password, shown once, to send them privately.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import EMAIL_RE, require_owner, require_team, user_payload
from app.config import get_company
from app.core.logging import get_logger
from app.core.security import generate_temporary_password, hash_password
from app.core.timezone import to_ist_string, utc_now
from app.db import crud
from app.db.database import get_session
from app.db.models import AccessRequest, Project, User
from app.notify.email_alert import send_sign_in_email

router = APIRouter(prefix="/api/admin", tags=["manage"])
log = get_logger("api.manage")

DEFAULT_STAGES = [
    "Discovery call", "Scope & estimate", "Design & approval",
    "Build", "Testing & launch", "Live & support",
]


def stages() -> list[str]:
    """The project stages, in order. company.yaml -> portal.stages, or the defaults."""
    return list(get_company().get("portal.stages", DEFAULT_STAGES) or DEFAULT_STAGES)


# =============================================================================
# Shared checks
# =============================================================================
def _clean_email(value: str) -> str:
    email = (value or "").strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That email address doesn't look right")
    return email


async def _create(session: AsyncSession, **fields) -> tuple[User, str]:  # noqa: ANN003
    """Makes the account with a fresh temporary password. Returns (user, that password)."""
    temp = generate_temporary_password()
    try:
        user = await crud.create_user(session, password_hash=hash_password(temp), temporary=True, **fields)
    except IntegrityError:
        #   Q: Why catch this instead of checking first?
        #   A: Checking first then inserting leaves a gap where two people add
        #      the same email at once. The database's UNIQUE rule is the real
        #      guard; we just turn its refusal into a friendly message.
        await session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "That email or username is already in use")
    return user, temp


def _account(user: User, temp: str = "", **extra) -> dict:  # noqa: ANN003
    """An account for the dashboard. `temp_password` appears ONLY in the reply that made it."""
    row = user_payload(user) | {"is_active": user.is_active} | extra
    expires = user.temp_password_expires_at
    # Waiting for first sign-in, but the temporary password is dead (7 days, or the email was fixed).
    row["temp_expired"] = bool(user.must_change_password and expires and expires < utc_now())
    if temp:
        row["temp_password"] = temp
    return row


def _sign_in_url(request: Request) -> str:
    """This site's /login address, as the person will type it — localhost now, the real domain later."""
    #   Q: Why read x-forwarded-proto?
    #   A: On Render the app sits behind a proxy and itself sees plain "http".
    #      The proxy tells us the visitor really used "https".
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    return f"{proto}://{request.url.netloc}/login"


async def _deliver(user: User, temp: str, request: Request, send: bool) -> dict:
    """Emails the sign-in details if asked. The account is made either way."""
    if not send:
        return {"email_sent": False, "email_detail": ""}
    sent, detail = await send_sign_in_email(user, temp, _sign_in_url(request))
    return {"email_sent": sent, "email_detail": detail}


# =============================================================================
# Team members — owner adds, everyone on the team can see the list
# =============================================================================
class NewTeamMember(BaseModel):
    email: str = Field(max_length=200)
    name: str = Field(default="", max_length=120)
    username: str = Field(default="", max_length=64)
    send_email: bool = True               # email them the sign-in details straight away


@router.get("/team")
async def list_team(
    _: User = Depends(require_team), session: AsyncSession = Depends(get_session)
) -> dict:
    people = await crud.list_users(session, ["owner", "team"])
    return {"team": [_account(u) for u in people]}


@router.post("/team")
async def add_team_member(
    payload: NewTeamMember,
    request: Request,
    owner: User = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> dict:
    user, temp = await _create(
        session,
        role="team",
        email=_clean_email(payload.email),
        username=payload.username,
        name=payload.name,
        created_by_id=owner.id,
    )
    log.info("team member added by %s", owner.name or owner.username)
    return {"user": _account(user, temp), **await _deliver(user, temp, request, payload.send_email)}


# =============================================================================
# Clients — owner or team
# =============================================================================
class NewClient(BaseModel):
    email: str = Field(max_length=200)
    name: str = Field(default="", max_length=120)
    company_name: str = Field(default="", max_length=160)
    send_email: bool = True


@router.get("/clients")
async def list_clients(
    _: User = Depends(require_team), session: AsyncSession = Depends(get_session)
) -> dict:
    clients = await crud.list_users(session, ["client"])
    projects = await crud.list_projects(session)
    count: dict[int, int] = {}
    for p in projects:
        count[p.client_id] = count.get(p.client_id, 0) + 1
    return {"clients": [_account(c, project_count=count.get(c.id, 0)) for c in clients]}


@router.post("/clients")
async def add_client(
    payload: NewClient,
    request: Request,
    member: User = Depends(require_team),
    session: AsyncSession = Depends(get_session),
) -> dict:
    user, temp = await _create(
        session,
        role="client",
        email=_clean_email(payload.email),
        name=payload.name,
        company_name=payload.company_name,
        created_by_id=member.id,
    )
    return {
        "user": _account(user, temp, project_count=0),
        **await _deliver(user, temp, request, payload.send_email),
    }


# =============================================================================
# Any account — switch off / on, fix details, new temporary password
# =============================================================================
class UserChange(BaseModel):
    is_active: bool | None = None
    name: str | None = Field(default=None, max_length=120)
    email: str | None = Field(default=None, max_length=200)          # fix a typo
    username: str | None = Field(default=None, max_length=64)
    company_name: str | None = Field(default=None, max_length=160)
    reset_password: bool = False          # true -> a new temporary password
    send_email: bool = False              # with reset_password: email it to them too


@router.patch("/users/{user_id}")
async def change_user(
    user_id: int,
    payload: UserChange,
    request: Request,
    me: User = Depends(require_team),
    session: AsyncSession = Depends(get_session),
) -> dict:
    target = await crud.get_user(session, user_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Account not found")

    # Team members may manage CLIENT accounts; only the owner manages the team.
    if target.role in {"owner", "team"} and me.role != "owner":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the owner can change team accounts")

    if payload.is_active is False:
        if target.id == me.id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "You can't switch off your own account")
        #   Q: Why protect the last owner?
        #   A: With no active owner, nobody could ever add or fix team accounts
        #      again without editing the database by hand.
        if target.role == "owner" and await crud.count_active_owners(session) <= 1:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "You can't switch off the last owner")

    if payload.is_active is not None:
        target.is_active = payload.is_active
    if payload.name is not None:
        target.name = payload.name.strip()
    if payload.company_name is not None:
        target.company_name = payload.company_name.strip()
    if payload.username is not None:
        target.username = payload.username.replace(" ", "") or None

    if payload.email is not None:
        email = _clean_email(payload.email)
        if email != (target.email or ""):
            target.email = email
            #   Q: Why forget their Google link when the email changes?
            #   A: The Google link belongs to the OLD address. Keeping it would
            #      block Google sign-in with the corrected one.
            target.google_sub = None
            #   Q: Why kill a waiting temporary password?
            #   A: If the email had a typo, the sign-in email may have gone to
            #      a STRANGER. Expiring it now means that stranger can't use it.
            #      "Email new sign-in details" then sends a fresh one to the right address.
            if target.must_change_password:
                target.temp_password_expires_at = utc_now()

    temp = ""
    if payload.reset_password:
        if target.id == me.id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "You can't reset your own password here")
        # "Forgot password": their old password stops working right now, and
        # they choose a new one when they sign in with this temporary one.
        temp = generate_temporary_password()
        crud.mark_temporary_password(target, hash_password(temp))

    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "That email or username is already used by another account")
    delivery = await _deliver(target, temp, request, bool(temp) and payload.send_email)
    return {"user": _account(target, temp), **delivery}


# =============================================================================
# Projects
# =============================================================================
def project_row(p: Project, client: User | None = None, members: list[User] | None = None) -> dict:
    return {
        "id": p.id,
        "client_id": p.client_id,
        "client_name": (client.name or client.email) if client else "",
        "client_company": client.company_name if client else "",
        "name": p.name,
        "summary": p.summary,
        "stage": p.stage,
        "progress": p.progress,
        "start_date": p.start_date.isoformat() if p.start_date else "",
        "target_date": p.target_date.isoformat() if p.target_date else "",
        "updated_at": to_ist_string(p.updated_at),
        "members": [{"id": m.id, "name": m.name or m.username or m.email} for m in (members or [])],
    }


def update_row(u) -> dict:  # noqa: ANN001
    return {
        "id": u.id,
        "title": u.title,
        "body": u.body,
        "author_name": u.author_name,
        "author_role": u.author_role,
        "created_at": to_ist_string(u.created_at),
    }


class ProjectFields(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    summary: str | None = Field(default=None, max_length=4000)
    stage: str | None = Field(default=None, max_length=48)
    progress: int | None = Field(default=None, ge=0, le=100)
    start_date: date | None = None
    target_date: date | None = None
    member_ids: list[int] | None = None       # who works on it — owner only


class NewProject(ProjectFields):
    client_id: int
    name: str = Field(min_length=1, max_length=200)


def _apply(project: Project, fields: ProjectFields) -> None:
    if fields.stage is not None and fields.stage not in stages():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Stage must be one of: {', '.join(stages())}")
    for key in ("name", "summary", "stage", "progress", "start_date", "target_date"):
        value = getattr(fields, key)
        if value is not None:
            setattr(project, key, value.strip() if isinstance(value, str) else value)


async def _check_members(session: AsyncSession, ids: list[int]) -> list[int]:
    """Only active owner/team accounts can be put on a project."""
    team = {u.id for u in await crud.list_users(session, ["owner", "team"]) if u.is_active}
    if any(i not in team for i in ids):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only active team members can be assigned")
    return ids


async def _visible_project(session: AsyncSession, project_id: int, me: User) -> Project:
    """The project — if this person may see it. The owner sees all; team only their own."""
    #   Q: Why "not found" for a team member's unassigned project, not "forbidden"?
    #   A: Same rule as the client portal: don't confirm what you can't see.
    project = await crud.get_project(session, project_id)
    if project is None or (
        me.role != "owner" and not await crud.is_project_member(session, project.id, me.id)
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    return project


async def _full_row(session: AsyncSession, project: Project) -> dict:
    client = await crud.get_user(session, project.client_id)
    members = (await crud.project_members(session, [project.id]))[project.id]
    return project_row(project, client, members)


@router.get("/projects")
async def list_projects(
    me: User = Depends(require_team), session: AsyncSession = Depends(get_session)
) -> dict:
    projects = await crud.list_projects(session, member_id=None if me.role == "owner" else me.id)
    clients = {c.id: c for c in await crud.list_users(session, ["client"])}
    members = await crud.project_members(session, [p.id for p in projects])
    return {
        "projects": [project_row(p, clients.get(p.client_id), members[p.id]) for p in projects],
        "stages": stages(),
    }


@router.post("/projects")
async def create_project(
    payload: NewProject,
    me: User = Depends(require_team),
    session: AsyncSession = Depends(get_session),
) -> dict:
    client = await crud.get_user(session, payload.client_id)
    if client is None or client.role != "client":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Choose a client for this project")
    project = Project(client_id=client.id, name=payload.name.strip(), stage=stages()[0])
    _apply(project, payload)
    session.add(project)
    await session.flush()                         # gives the project its id, not saved yet

    # The owner picks the people. A team member who creates a project is put on
    # it automatically — otherwise it would vanish from their own list.
    if me.role == "owner":
        ids = await _check_members(session, payload.member_ids or [])
    else:
        ids = [me.id]
    await crud.set_project_members(session, project.id, ids)
    await session.commit()
    log.info("project %s created for client %s", project.id, client.id)
    return {"project": await _full_row(session, project)}


@router.get("/projects/{project_id}")
async def project_detail(
    project_id: int, me: User = Depends(require_team), session: AsyncSession = Depends(get_session)
) -> dict:
    project = await _visible_project(session, project_id, me)
    updates = await crud.project_updates(session, project.id)
    return {
        "project": await _full_row(session, project),
        "updates": [update_row(u) for u in updates],
        "stages": stages(),
    }


@router.patch("/projects/{project_id}")
async def change_project(
    project_id: int,
    payload: ProjectFields,
    me: User = Depends(require_team),
    session: AsyncSession = Depends(get_session),
) -> dict:
    project = await _visible_project(session, project_id, me)
    _apply(project, payload)
    if payload.member_ids is not None:
        if me.role != "owner":
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the owner assigns people to projects")
        await crud.set_project_members(session, project.id, await _check_members(session, payload.member_ids))
    await session.commit()
    return {"project": await _full_row(session, project)}


@router.delete("/projects/{project_id}")
async def delete_project(
    project_id: int, _: User = Depends(require_owner), session: AsyncSession = Depends(get_session)
) -> dict:
    """Owner only: a client's whole history goes with it."""
    project = await crud.get_project(session, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    await session.delete(project)               # its updates and assignments go with it (cascade)
    await session.commit()
    return {"status": "deleted"}


class NewUpdate(BaseModel):
    title: str = Field(default="", max_length=200)
    body: str = Field(min_length=1, max_length=8000)


@router.post("/projects/{project_id}/updates")
async def post_update(
    project_id: int,
    payload: NewUpdate,
    me: User = Depends(require_team),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """A team update the client will see in their portal."""
    project = await _visible_project(session, project_id, me)
    update = await crud.add_project_update(session, project, me, title=payload.title, body=payload.body)
    return {"update": update_row(update)}


# =============================================================================
# Access requests — from the "Request access" link on the sign-in page
# =============================================================================
def request_row(r: AccessRequest) -> dict:
    return {
        "id": r.id,
        "name": r.name,
        "email": r.email,
        "company_name": r.company_name,
        "message": r.message,
        "status": r.status,
        "handled_by": r.handled_by_name,
        "handled_at": to_ist_string(r.handled_at),
        "created_at": to_ist_string(r.created_at),
    }


async def _pending_request(session: AsyncSession, request_id: int) -> AccessRequest:
    req = await crud.get_access_request(session, request_id)
    if req is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Request not found")
    if req.status != "pending":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Already {req.status}")
    return req


def _close(req: AccessRequest, me: User, outcome: str) -> None:
    req.status = outcome
    req.handled_by_name = me.name or me.username or me.email or ""
    req.handled_at = utc_now()


@router.get("/requests")
async def list_requests(
    _: User = Depends(require_team), session: AsyncSession = Depends(get_session)
) -> dict:
    return {"requests": [request_row(r) for r in await crud.list_access_requests(session)]}


class RequestChange(BaseModel):
    """Fix a request's details (a typo in the email, say) BEFORE approving it."""

    name: str | None = Field(default=None, min_length=1, max_length=120)
    email: str | None = Field(default=None, max_length=200)
    company_name: str | None = Field(default=None, max_length=160)


@router.patch("/requests/{request_id}")
async def change_request(
    request_id: int,
    payload: RequestChange,
    _: User = Depends(require_team),
    session: AsyncSession = Depends(get_session),
) -> dict:
    req = await _pending_request(session, request_id)
    if payload.name is not None:
        req.name = payload.name.strip()
    if payload.email is not None:
        req.email = _clean_email(payload.email)
    if payload.company_name is not None:
        req.company_name = payload.company_name.strip()
    await session.commit()
    return {"request": request_row(req)}


class Approval(BaseModel):
    send_email: bool = True


@router.post("/requests/{request_id}/approve")
async def approve_request(
    request_id: int,
    request: Request,
    payload: Approval | None = None,
    me: User = Depends(require_team),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Makes the CLIENT account (with a temporary password), emails it, and closes the request."""
    req = await _pending_request(session, request_id)
    if await crud.get_user_by_email(session, req.email):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This email already has an account. Reject the request, or reset that account's password.",
        )
    _close(req, me, "approved")
    user, temp = await _create(
        session,
        role="client",
        email=req.email,
        name=req.name,
        company_name=req.company_name,
        created_by_id=me.id,
    )                                             # _create commits, saving the request too
    log.info("access request %s approved by %s", req.id, me.id)
    send = payload.send_email if payload else True
    return {
        "request": request_row(req),
        "user": _account(user, temp, project_count=0),
        **await _deliver(user, temp, request, send),
    }


@router.post("/requests/{request_id}/reject")
async def reject_request(
    request_id: int, me: User = Depends(require_team), session: AsyncSession = Depends(get_session)
) -> dict:
    req = await _pending_request(session, request_id)
    _close(req, me, "rejected")
    await session.commit()
    return {"request": request_row(req)}
