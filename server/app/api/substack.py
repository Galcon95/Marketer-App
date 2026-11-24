"""The author's own Substack publication (social/substack.py), saved with the project: its latest posts for Community
("My Substack"), and its name, so Scan Substack leaves the author's own posts out.

    GET    /projects/{id}/substack   the publication and its latest posts ({"publication": ""} when none is set)
    PUT    /projects/{id}/substack   set it (checked: its feed must exist)
    DELETE /projects/{id}/substack   forget it

No model call and no cost: the posts come from the publication's public RSS feed.
"""

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import owned_project
from app.core import state as db
from app.core.schemas import Project, SubstackFeed, SubstackRequest
from app.db import records
from app.social import substack

router = APIRouter()


@router.get("/projects/{project_id}/substack", response_model=SubstackFeed)
def get_substack(project: Project = Depends(owned_project)):
    """The project's Substack publication with its latest posts (newest first); no publication: empty.

    Raises:
        HTTPException: 404 if the project is unknown or another user's, or the publication no longer exists; 502 if
            its feed cannot be read; 504 on a timeout.
    """
    if not project.substack:
        return SubstackFeed()
    return _feed(project.substack)


@router.put("/projects/{project_id}/substack", response_model=SubstackFeed)
def set_substack(body: SubstackRequest, project: Project = Depends(owned_project)):
    """Save the author's Substack publication after reading its feed once (so a typo is caught).

    Raises:
        HTTPException: 422 if the address is no Substack publication or none exists there; 502/504 if Substack fails;
            500 if it cannot be saved.
    """
    try:
        name = substack.publication_name(body.address)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    try:
        feed = _feed(name)
    except HTTPException as e:
        if e.status_code == 404:
            raise HTTPException(422, f"There is no Substack publication at {name}.substack.com.") from e
        raise
    _save(project.model_copy(update={"substack": name}))
    return feed


@router.delete("/projects/{project_id}/substack", status_code=204)
def delete_substack(project: Project = Depends(owned_project)):
    """Forget the project's Substack publication. 500 if it cannot be saved."""
    _save(project.model_copy(update={"substack": ""}))


def _feed(name: str) -> SubstackFeed:
    try:
        posts = substack.latest_posts(name)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    except substack.SubstackError as e:
        raise HTTPException(e.status_code, str(e)) from e
    return SubstackFeed(publication=name, url=f"https://{name}.substack.com", posts=posts)


def _save(project: Project) -> None:
    """Save the project (database first; memory only when that worked)."""
    stored = project.model_copy(update={"source_count": 0, "chunk_count": 0, "asset_count": 0, "token_count": 0})
    try:
        records.save_project(stored)
    except OSError as e:  # DatabaseError
        raise HTTPException(500, "Could not save your Substack, please try again.") from e
    db.projects[project.id] = stored
