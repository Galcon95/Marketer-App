"""Projects (marketing campaigns) with their live source, chunk, asset and token counts."""

from fastapi import APIRouter

from app.api.deps import get_project_or_404
from app.core import state as db
from app.core.schemas import Project, ProjectCreate

router = APIRouter()


# ---------- Projects ----------
@router.post("/projects", response_model=Project, status_code=201)
def create_project(body: ProjectCreate):
    """Create a new, empty project.

    Args:
        body: Name and optional description of the project.

    Returns:
        The created project with a new "prj_" id and zero counts.
    """
    project = Project(id=db.new_id("prj"), name=body.name, description=body.description, created_at=db.now())
    db.projects[project.id] = project
    return project


@router.get("/projects", response_model=list[Project])
def list_projects():
    """List all projects, each with its current source, chunk and asset counts."""
    return [with_counts(p) for p in db.projects.values()]


@router.get("/projects/{project_id}", response_model=Project)
def get_project(project_id: str):
    """Return one project with its current counts.

    Args:
        project_id: Id of the project (path parameter). 404 if unknown.
    """
    return with_counts(get_project_or_404(project_id))


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
