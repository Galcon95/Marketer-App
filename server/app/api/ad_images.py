"""Ad pictures of the assets: make one with the image model (core/ad_images.py), list them, show one, delete one."""

from fastapi import APIRouter, Depends, HTTPException, Response

from app.api.deps import checked_optional, llm_limits, owned_ad_image, owned_asset
from app.core import ad_images
from app.core.llm import GenerationError
from app.core.schemas import AdImage, AdImageRequest, Asset
from app.db import records

router = APIRouter()


@router.post("/assets/{asset_id}/images", response_model=AdImage, status_code=201, dependencies=[Depends(llm_limits)])
def create_ad_image(body: AdImageRequest, asset: Asset = Depends(owned_asset)):
    """Make an ad picture for an asset: the book's cover in a scene that fits the book, with the headline drawn in
    (or no text) in the chosen format. Costs one image model call (about $0.07 with the default model), counted
    against the user's budgets like every model call.

    Args:
        asset_id: Id of the asset (path parameter), e.g. an ad copy.
        body: Book (optional when the asset has one book), headline ("" = no text), scene wish, format.

    Returns:
        The picture's record; the picture itself is at GET /ad-images/{id}.

    Raises:
        HTTPException: 400 if the headline or scene is a likely prompt injection; 404 for an unknown asset or book;
            422 if the headline is longer than 80 characters or the asset has several books and none was chosen;
            429 if a budget or the rate limit is reached; 503 if no image model is configured; 502 if the model
            failed or sent no picture; 504 if it timed out; 500 if the picture cannot be saved.
    """
    body = body.model_copy(update={
        # The author's own words for the model: checked for prompt injection like a brief.
        "headline": checked_optional(body.headline, "short_text", "headline"),
        "scene": checked_optional(body.scene, "short_text", "scene"),
    })
    try:
        return ad_images.create(asset, body)
    except ad_images.AdImageError as e:
        raise HTTPException(e.status_code, str(e)) from e
    except GenerationError as e:
        raise HTTPException(e.status_code, str(e)) from e
    except OSError as e:  # FileStoreError, DatabaseError
        raise HTTPException(500, "The picture was made but could not be saved, please try again.") from e


@router.get("/assets/{asset_id}/images", response_model=list[AdImage])
def list_ad_images(asset: Asset = Depends(owned_asset)):
    """The ad pictures of an asset, oldest first. 404 for an unknown asset; 500 if the database cannot be read."""
    try:
        return records.ad_images([asset.id])
    except OSError as e:  # DatabaseError
        raise HTTPException(500, "The pictures could not be loaded, please try again.") from e


@router.get("/ad-images/{image_id}", response_class=Response,
            responses={200: {"content": {"image/png": {}}}})
def get_ad_image(image: AdImage = Depends(owned_ad_image)):
    """The picture itself (PNG). 404 if unknown, not the user's or its file is missing; 503 if Storage cannot be
    reached. The browser may keep it: a picture never changes (a new one gets a new id)."""
    try:
        png = ad_images.picture(image)
    except OSError as e:  # FileStoreError
        raise HTTPException(503, "The file storage cannot be reached, please try again.") from e
    if png is None:
        raise HTTPException(404, "The file of this picture is missing")
    return Response(png, media_type="image/png", headers={
        "Cache-Control": "private, max-age=86400, immutable",
        "Content-Disposition": f'inline; filename="{image.id}.png"',
    })


@router.delete("/ad-images/{image_id}", status_code=204)
def delete_ad_image(image: AdImage = Depends(owned_ad_image)):
    """Delete a picture (its record, then its file). 404 if unknown or not the user's; 500 if it cannot be deleted."""
    try:
        records.delete_ad_image(image.id)
    except OSError as e:  # DatabaseError
        raise HTTPException(500, "The picture could not be deleted, please try again.") from e
    ad_images.delete_files([ad_images.image_path(image)])
