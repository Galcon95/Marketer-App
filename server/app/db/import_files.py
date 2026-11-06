"""One-time import of the old JSON files into the database: projects.json and api_keys.json in server/assets/.

    uv run python -m app.db.import_files        (from server/, after `uv run alembic upgrade head`)

Records already in the database (same id) are left as they are, so running it twice changes nothing. The files are
not changed; once the app works with the database, delete them (or keep a copy outside the project).
"""

import json
import sys
from pathlib import Path

from sqlalchemy import select

from app.core.config import DATA_DIR
from app.core.schemas import ApiKey, Project
from app.db.database import session
from app.db.tables import ApiKeyRow, ProjectRow

PROJECTS_FILE = DATA_DIR / "projects.json"
KEYS_FILE = DATA_DIR / "api_keys.json"


def _read(path: Path) -> list[dict]:
    if not path.is_file():
        print(f"{path.name}: not found, nothing to import")
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def import_projects(path: Path = PROJECTS_FILE) -> int:
    """Insert the projects of projects.json that are not in the database yet; returns how many."""
    projects = [Project.model_validate(p) for p in _read(path)]
    with session() as s:
        known = set(s.scalars(select(ProjectRow.id)))
        new = [p for p in projects if p.id not in known]
        s.add_all(ProjectRow(id=p.id, name=p.name, description=p.description, created_at=p.created_at,
                             owner_id=p.owner_id or None) for p in new)
    return len(new)


def import_api_keys(path: Path = KEYS_FILE) -> int:
    """Insert the keys of api_keys.json (hashes) that are not in the database yet; returns how many."""
    keys = [ApiKey.model_validate(k) for k in _read(path)]
    with session() as s:
        known = set(s.scalars(select(ApiKeyRow.id)))
        new = [k for k in keys if k.id not in known]
        s.add_all(ApiKeyRow(**k.model_dump()) for k in new)
    return len(new)


def main() -> None:
    try:
        print(f"projects: {import_projects()} imported")
        print(f"API keys: {import_api_keys()} imported")
    except OSError as e:  # DatabaseError
        sys.exit(f"Import failed: {e} ({e.__cause__})")


if __name__ == "__main__":
    main()
