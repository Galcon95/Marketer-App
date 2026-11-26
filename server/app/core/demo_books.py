"""The books of the public demo's guest (core/guest.py): copies of books that are already in the app, with their
files, cover, summary and chunks with embeddings, so the demo costs nothing to set up (nothing is embedded or
summarized again). Run by scripts/make_guest_demo.py; "Try as guest" keeps them when it starts the demo afresh.

Only public-domain books belong here: every visitor can read them and open the PDF.
"""

import logging

from app.core import files
from app.core import state as db
from app.core.schemas import Project, Source
from app.db import records

logger = logging.getLogger(__name__)

# The admin's public-domain books the demo copies when the script is given none.
DEFAULT_BOOKS = ("ThePrinciplesOfPoliticalEconomy.pdf", "The-Evolution-of-Man_Ernst-Haeckel.pdf")


def copy_book(source: Source, project: Project) -> Source | None:
    """Copy a ready book into the project: the source record, its files (book and cover), its summary and its chunks
    with their embeddings. A book whose file is already in the project (same checksum or name) is skipped.

    Returns:
        The new source, or None if the project already has the book.

    Raises:
        ValueError: If the book is not ready (no chunks to copy).
        DatabaseError, FileStoreError: If the database or Storage refuses; the half-made copy is then deleted again.
    """
    if source.status != "ready":
        raise ValueError(f"{source.filename} is not ready ({source.status}); only ready books can be copied.")
    for other in records.load_sources().values():
        if other.project_id == project.id and (other.filename == source.filename
                                               or (source.sha256 and other.sha256 == source.sha256)):
            return None
    copy = source.model_copy(update={"id": db.new_id("src"), "project_id": project.id, "created_at": db.now()})
    records.add_source(copy)
    try:
        names = files.copy_source_files(source.project_id, source.id, project.id, copy.id)
        if not any(name.startswith("book.") for name in names):
            raise FileNotFoundError(f"The file of {source.filename} is missing in Storage.")
        if summary := records.load_summaries().get(source.id):
            records.save_summary(summary.model_copy(update={"source_id": copy.id}))
        copied = records.copy_chunks(source.id, copy.id, project.id)
        if copied != source.chunk_count:
            logger.warning("%s: %d chunks copied, the source says %d", source.filename, copied, source.chunk_count)
    except Exception:
        records.delete_chunks(copy.id)
        records.delete_source(copy.id)
        files.delete_source_files(project.id, copy.id)
        raise
    return copy
