"""Accounts: which project (client) belongs to which signed-in user. Each user owns exactly one project.

On a user's first request (GET /me), client_of creates their project, named after their email. The default project
("demo-campaign": the books, assets and chats from before sign-in existed) goes to the user whose email is
DEFAULT_CLIENT_OWNER instead; that user is also the app's admin (app-wide usage and costs, MCP console).
Projects and their owners are saved in the database (table projects; app/db/records.py).
"""

import logging
import threading

from app.core import state as db
from app.core.auth import User
from app.core.config import DEFAULT_CLIENT_OWNER
from app.core.schemas import Project
from app.db import records

logger = logging.getLogger(__name__)

_lock = threading.Lock()  # sync endpoints run in a thread pool: two first requests must not create two projects


def is_admin(user: User) -> bool:
    """True for the user whose email is DEFAULT_CLIENT_OWNER (nobody if it is not set)."""
    return bool(DEFAULT_CLIENT_OWNER) and user.email.lower() == DEFAULT_CLIENT_OWNER


def owns(user: User, project: Project) -> bool:
    """True if the project belongs to this user."""
    return bool(project.owner_id) and project.owner_id == user.id


def client_of(user: User) -> Project:
    """The user's project: the one they own, else the default project (for DEFAULT_CLIENT_OWNER, if nobody owns it
    yet), else a new, empty one named after their email. A new or newly claimed project is saved.

    Raises:
        DatabaseError: If the project cannot be saved.
    """
    with _lock:
        own = next((p for p in db.projects.values() if owns(user, p)), None)
        if own:
            return own
        default = db.projects.get(db.DEFAULT_PROJECT_ID)
        if is_admin(user) and default and not default.owner_id:
            project = default.model_copy(update={"owner_id": user.id})
            logger.info("The default project %s now belongs to %s", project.id, user.email)
        else:
            project = Project(id=db.new_id("prj"), name=user.email or "My library", description="",
                              created_at=db.now(), owner_id=user.id)
            logger.info("Created project %s for a new user", project.id)
        records.save_project(project)  # first in the database: if that fails, nothing has changed
        db.projects[project.id] = project
        return project
