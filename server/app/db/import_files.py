"""One-time import of the old JSON files in server/assets/ into the database: projects.json, api_keys.json,
generated/{project_id}/*.json (assets), conversations/{project_id}/*.json (chats), usage/usage.jsonl (the
model calls and their costs) and from uploads/{project_id}/{source_id}/ the book records (.source.json; recovered
from the PDF if missing) and summaries (.summary.json). The PDFs, chunks and covers stay where they are.

    uv run python -m app.db.import_files        (from server/, after `uv run alembic upgrade head`)

Records already in the database (same id; for model calls, which have no id: the same time, operation and model)
are left as they are, so running it twice changes nothing. Assets and
chats of a project that is not in the database are skipped (they would belong to nobody); so are books whose
file is already in the project under another id (the database allows the same file only once per project). The files are not changed;
once the app works with the database, delete them (or keep a copy outside the project).
"""

import json
import sys
from pathlib import Path

from sqlalchemy import select

from app.core import storage
from app.core.config import DATA_DIR
from app.core.schemas import ApiKey, Asset, Conversation, Project, UsageRecord
from app.db import records
from app.db.database import session
from app.db.tables import ApiKeyRow, AssetRow, ConversationRow, ProjectRow, SourceRow, SummaryRow, UsageRow

PROJECTS_FILE = DATA_DIR / "projects.json"
KEYS_FILE = DATA_DIR / "api_keys.json"
GENERATED_DIR = DATA_DIR / "generated"
CONVERSATIONS_DIR = DATA_DIR / "conversations"
USAGE_FILE = DATA_DIR / "usage" / "usage.jsonl"


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


def _read_dir(folder: Path, model) -> list:
    if not folder.is_dir():
        print(f"{folder.name}/: not found, nothing to import")
        return []
    return [model.model_validate_json(path.read_text(encoding="utf-8")) for path in sorted(folder.glob("*/*.json"))]


def _import_dir(folder: Path, model, row_class, json_fields: set[str]) -> int:
    """Insert the records of folder/{project_id}/*.json that are not in the database yet; returns how many."""
    items = _read_dir(folder, model)
    with session() as s:
        known = set(s.scalars(select(row_class.id)))
        projects = set(s.scalars(select(ProjectRow.id)))
        new = [i for i in items if i.id not in known and i.project_id in projects]
        for skipped in {i.project_id for i in items if i.project_id not in projects}:
            print(f"{folder.name}/{skipped}: no such project in the database, skipped")
        s.add_all(records.to_row(row_class, i, json_fields) for i in new)
    return len(new)


def import_assets(folder: Path = GENERATED_DIR) -> int:
    """Insert the generated assets that are not in the database yet; returns how many."""
    return _import_dir(folder, Asset, AssetRow, records.ASSET_JSON_FIELDS)


def import_conversations(folder: Path = CONVERSATIONS_DIR) -> int:
    """Insert the "Ask your book" chats that are not in the database yet; returns how many."""
    return _import_dir(folder, Conversation, ConversationRow, records.CONVERSATION_JSON_FIELDS)


def import_usage(path: Path = USAGE_FILE) -> int:
    """Insert the model calls of usage.jsonl that are not in the database yet; returns how many. Unreadable lines
    are skipped, as the app always did."""
    if not path.is_file():
        print(f"{path.name}: not found, nothing to import")
        return 0
    calls = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            calls.append(UsageRecord.model_validate_json(line))
        except ValueError:  # ValidationError
            continue
    with session() as s:
        known = {tuple(row) for row in s.execute(select(UsageRow.timestamp, UsageRow.operation, UsageRow.model))}
        new = [c for c in calls if (c.timestamp, c.operation, c.model) not in known]
        s.add_all(UsageRow(**c.model_dump()) for c in new)
    return len(new)


def import_sources() -> tuple[int, int]:
    """Insert the book records of the upload folders (storage.UPLOAD_DIR) and their summaries that are not in the
    database yet; returns (books, summaries)."""
    sources = storage.load_sources()  # reads .source.json, or recovers the record from the PDF
    with session() as s:
        known = set(s.scalars(select(SourceRow.id)))
        projects = set(s.scalars(select(ProjectRow.id)))
        files = {(r.project_id, r.sha256) for r in s.scalars(select(SourceRow)) if r.sha256}
        summarized = set(s.scalars(select(SummaryRow.source_id)))
        new_sources, new_summaries = [], []
        for source in sources.values():
            if source.id in known:
                pass
            elif source.project_id not in projects:
                print(f"uploads/{source.project_id}/{source.id}: no such project in the database, skipped")
                continue
            elif source.sha256 and (source.project_id, source.sha256) in files:
                print(f"uploads/{source.project_id}/{source.id}: the same file is already in the project, skipped")
                continue
            else:
                new_sources.append(source)
                files.add((source.project_id, source.sha256))
            if source.id not in summarized and (summary := storage.load_summary(source)):
                new_summaries.append(summary)
        s.add_all(records.to_row(SourceRow, x, set()) for x in new_sources)
        s.flush()  # the books first: their summaries refer to them
        s.add_all(records.to_row(SummaryRow, x, records.SUMMARY_JSON_FIELDS) for x in new_summaries)
    return len(new_sources), len(new_summaries)


def main() -> None:
    try:
        print(f"projects: {import_projects()} imported")
        print(f"API keys: {import_api_keys()} imported")
        print(f"assets: {import_assets()} imported")
        print(f"conversations: {import_conversations()} imported")
        print(f"model calls: {import_usage()} imported")
        books, summaries = import_sources()
        print(f"books: {books} imported, summaries: {summaries} imported")
    except OSError as e:  # DatabaseError
        sys.exit(f"Import failed: {e} ({e.__cause__})")


if __name__ == "__main__":
    main()
