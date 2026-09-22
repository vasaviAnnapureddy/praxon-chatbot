"""
The CUSTOMER side: what a Praxon client sees after logging in at /portal.

    GET  /api/portal/projects                 my projects
    GET  /api/portal/projects/{id}            one project + its updates
    POST /api/portal/projects/{id}/messages   reply to the team

Every route uses require_client (only role "client" gets in), and every query is
filtered to projects where client_id == the logged-in person. There is no way to
ask for "all projects" from here.

  Q: A client asks for someone else's project id. Why "not found", not "forbidden"?
  A: "Forbidden" would confirm that project exists. "Not found" tells them
     nothing about other clients at all.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import require_client
from app.api.manage import project_row, stages, update_row
from app.core.logging import get_logger
from app.db import crud
from app.db.database import get_session
from app.db.models import Project, User

router = APIRouter(prefix="/api/portal", tags=["portal"])
log = get_logger("api.portal")


async def _my_project(session: AsyncSession, project_id: int, me: User) -> Project:
    """The project — only if it belongs to the person asking."""
    project = await crud.get_project(session, project_id)
    if project is None or project.client_id != me.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    return project


@router.get("/projects")
async def my_projects(
    me: User = Depends(require_client), session: AsyncSession = Depends(get_session)
) -> dict:
    projects = await crud.list_projects(session, client_id=me.id)
    return {"projects": [project_row(p, me) for p in projects], "stages": stages()}


@router.get("/projects/{project_id}")
async def my_project(
    project_id: int, me: User = Depends(require_client), session: AsyncSession = Depends(get_session)
) -> dict:
    project = await _my_project(session, project_id, me)
    updates = await crud.project_updates(session, project.id)
    return {
        "project": project_row(project, me),
        "updates": [update_row(u) for u in updates],
        "stages": stages(),
    }


class ClientMessage(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


@router.post("/projects/{project_id}/messages")
async def reply_to_team(
    project_id: int,
    payload: ClientMessage,
    me: User = Depends(require_client),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """The client's reply lands in the same timeline the team sees."""
    project = await _my_project(session, project_id, me)
    update = await crud.add_project_update(session, project, me, title="", body=payload.body)
    log.info("client %s replied on project %s", me.id, project.id)
    return {"update": update_row(update)}
