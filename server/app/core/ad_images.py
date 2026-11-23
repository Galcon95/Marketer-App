"""Ad pictures of the assets: made by core/images.py, stored, listed and deleted.

    create(asset, request)  →  AdImage    the picture as a PNG in Storage at {project_id}/ads/{id}.png, its record in
                                          the database (table ad_images)

The book whose cover and summary go into the picture is the request's source_id, or else the asset's only book. Every
picture is stored as a PNG made again from its pixels (ingestion.to_png), so what is served is never the model's
bytes as they came. A picture's record is deleted with its asset (also when the asset goes with its book or campaign
kit); delete_files removes the stored pictures then.
"""

import logging

from app.core import files, images, usage
from app.core import state as db
from app.core.llm import GenerationError
from app.core.schemas import AdImage, AdImageRequest, Asset
from app.db import records
from app.rag import ingestion
from app.rag.retrieval import source_name

logger = logging.getLogger(__name__)

MAX_ABOUT_CHARS = 2000  # of the book summary given to the image model as background
MAX_PICTURE_HEIGHT = 2048  # px; the models make at most about 2K


class AdImageError(Exception):
    """A request for a picture cannot be served; carries the HTTP status the API should return."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code


def image_path(image: AdImage) -> str:
    """Object name of a picture in Storage."""
    return f"{image.project_id}/ads/{image.id}.png"


def choose_book(asset: Asset, source_id: str | None) -> str:
    """The id of the book a picture is made for: the requested one (it must be one of the asset's books, or of its
    project for an asset made from all books), else the asset's only book.

    Raises:
        AdImageError: 404 for a book that is not the asset's; 422 if the asset has several books and none was chosen.
    """
    if source_id:
        source = db.sources.get(source_id)
        allowed = asset.source_ids or [s.id for s in db.sources.values() if s.project_id == asset.project_id]
        if source is None or source.project_id != asset.project_id or source_id not in allowed:
            raise AdImageError(404, f"Source '{source_id}' not found")
        return source_id
    if len(asset.source_ids) == 1 and asset.source_ids[0] in db.sources:
        return asset.source_ids[0]
    raise AdImageError(422, "This asset is not about one book: choose the book whose cover the picture shows.")


def about_book(source_id: str) -> str:
    """What the book is about for the image model: its summary and themes (shortened), or "" without a summary."""
    summary = db.summaries.get(source_id)
    if summary is None:
        return ""
    text = summary.summary + ("\nThemes: " + ", ".join(summary.themes) if summary.themes else "")
    return text[:MAX_ABOUT_CHARS]


def create(asset: Asset, request: AdImageRequest) -> AdImage:
    """Make a picture for an asset, store it and save its record.

    The request's headline and scene must already be checked (api/deps.checked_optional).

    Raises:
        AdImageError: 404/422 for the book (choose_book); 422 for a headline or scene the image module refuses.
        GenerationError: From the image model (503 not configured, 504 timeout, 502 failed or no picture).
        OSError: If the picture or its record cannot be saved (FileStoreError, DatabaseError).
    """
    source_id = choose_book(asset, request.source_id)
    source = db.sources[source_id]
    cover = ingestion.cover(source)
    try:
        with usage.tagged(asset_id=asset.id, asset_type=asset.asset_type, source_id=source_id):
            made = images.generate_ad_image(
                book=source_name(source_id) or source.filename, about=about_book(source_id),
                headline=request.headline, scene=request.scene, fmt=request.format, cover=cover,
                project_id=asset.project_id, source_id=source_id)
    except ValueError as e:
        raise AdImageError(422, str(e)) from e
    try:
        png = ingestion.to_png(made.data, max_height=MAX_PICTURE_HEIGHT)
    except (ValueError, TimeoutError) as e:
        raise GenerationError(502, f"The picture could not be read: {e}") from e
    image = AdImage(id=db.new_id("img"), project_id=asset.project_id, asset_id=asset.id,
                    source_id=source_id, format=request.format, headline=request.headline, scene=request.scene,
                    model=made.model, prompt_version=made.prompt_version, cost=made.cost, created_at=db.now())
    files.put(image_path(image), png, "image/png")
    try:
        records.save_ad_image(image)
    except OSError:
        delete_files([image_path(image)])  # no record, no file
        raise
    return image


def picture(image: AdImage) -> bytes | None:
    """The stored PNG of a picture, or None if it is missing.

    Raises:
        FileStoreError: If Storage cannot be reached.
    """
    return files.get(image_path(image))


def delete_files(paths: list[str]) -> None:
    """Delete stored pictures; a failure is only logged (they are then orphaned in Storage, but unreachable)."""
    if not paths:
        return
    try:
        files.delete(paths)
    except OSError as e:  # FileStoreError
        logger.warning("Could not delete %d ad picture(s): %s", len(paths), e)


def paths_of(asset_ids: list[str]) -> list[str]:
    """The stored pictures of these assets, read before the assets are deleted (their records go with them).
    Database errors are only logged (the pictures are then orphaned)."""
    try:
        return [image_path(image) for image in records.ad_images(asset_ids)]
    except OSError as e:  # DatabaseError
        logger.warning("Could not list the ad pictures of %d asset(s): %s", len(asset_ids), e)
        return []
