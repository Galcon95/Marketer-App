"""The signed-in user and their project (client) with its live source, chunk, asset and token counts. Each user
has exactly one project (accounts.py); it is created on their first GET /me."""

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import owned_project
from app.core import accounts
from app.core import state as db
from app.core.auth import User, current_user
from app.core.schemas import Me, Project

router = APIRouter()


# ---------- Signed-in user ----------
@router.get("/me", response_model=Me)
def me(user: User = Depends(current_user)):
    """The signed-in user with their project (created on the first call) and whether they are the admin.

    Raises:
        HTTPException: 500 if a new project cannot be saved.
    """
    try:
        project = accounts.client_of(user)
    except OSError as e:
        raise HTTPException(500, "Your library could not be created, please try again.") from e
    return Me(user_id=user.id, email=user.email, admin=accounts.is_admin(user), project=with_counts(project))


# ---------- Projects ----------
@router.get("/projects", response_model=list[Project])
def list_projects(user: User = Depends(current_user)):
    """List the user's projects (one), each with its current source, chunk and asset counts."""
    return [with_counts(p) for p in db.projects.values() if accounts.owns(user, p)]


@router.get("/projects/{project_id}", response_model=Project)
def get_project(project: Project = Depends(owned_project)):
    """Return one of the user's projects with its current counts. 404 if unknown or another user's."""
    return with_counts(project)


def with_counts(project: Project) -> Project:
    """Return a copy of a project with source_count, chunk_count, asset_count and token_count filled in.

    Counts are computed on every call by scanning the in-memory stores, so they are always
    current; the stored project itself is not modified.

    Args:
        project: The project to count for.

    Returns:
        A new Project instance with up-to-date counts.
    """
    source_ids = {s.id for s in db.sources.values() if s.project_id == project.id}
    return project.model_copy(update={
        "source_count": len(source_ids),
        "chunk_count": sum(1 for c in db.chunks.values() if c.source_id in source_ids),
        "asset_count": sum(1 for a in db.assets.values() if a.project_id == project.id),
        "token_count": sum(a.tokens for a in db.assets.values() if a.project_id == project.id)
                       + sum(s.tokens for sid, s in db.summaries.items() if sid in source_ids),
    })
