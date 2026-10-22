"""Generated assets: single-asset generation (grounded or zero-shot) and asset management."""

from fastapi import APIRouter, HTTPException

from app.api.deps import get_project_or_404
from app.core import state as db
from app.core import storage
from app.core.llm import GenerationError
from app.core.schemas import Asset, AssetUpdate, GenerateRequest
from app.rag import generation

router = APIRouter()


# ---------- Generation & assets ----------
@router.post("/projects/{project_id}/generate", response_model=Asset, status_code=201)
def generate(project_id: str, body: GenerateRequest):
    """Generate a marketing asset from a brief with the LLM and store it in the project.

    Runs the LangGraph in generation.py. Grounded (RAG): the brief retrieves the k most similar
    chunks, which go into the prompt as numbered excerpts; the model cites them, and the cited ones
    become the asset's citations. Zero-shot: the model writes from the brief alone.

    Args:
        project_id: Id of the project (path parameter). 404 if unknown.
        body: Asset type, brief, grounded flag and number of context chunks k.

    Returns:
        The newly created Asset, also saved to disk (storage.write_asset).

    Raises:
        HTTPException: 503 if no API key is configured; 502 if retrieval or the model call fails.
    """
    get_project_or_404(project_id)
    try:
        return generation.create_asset(project_id, body)
    except GenerationError as e:
        raise HTTPException(e.status_code, str(e)) from e
    except OSError as e:
        raise HTTPException(500, "The asset was generated but could not be saved") from e


@router.get("/projects/{project_id}/assets", response_model=list[Asset])
def list_assets(project_id: str):
    """List all generated assets of a project.

    Args:
        project_id: Id of the project (path parameter). 404 if unknown.
    """
    get_project_or_404(project_id)
    return [a for a in db.assets.values() if a.project_id == project_id]


@router.get("/assets/{asset_id}", response_model=Asset)
def get_asset(asset_id: str):
    """Return one generated asset.

    Args:
        asset_id: Id of the asset (path parameter).

    Raises:
        HTTPException: 404 when no asset has this id.
    """
    asset = db.assets.get(asset_id)
    if asset is None:
        raise HTTPException(404, f"Asset '{asset_id}' not found")
    return asset


@router.patch("/assets/{asset_id}", response_model=Asset)
def update_asset(asset_id: str, body: AssetUpdate):
    """Replace the text of a generated asset with the user's edited version (citations are kept).

    Args:
        asset_id: Id of the asset (path parameter).
        body: The new text.

    Raises:
        HTTPException: 404 when no asset has this id; 500 if it cannot be saved.
    """
    asset = db.assets.get(asset_id)
    if asset is None:
        raise HTTPException(404, f"Asset '{asset_id}' not found")
    asset = asset.model_copy(update={"text": body.text, "edited": True})
    try:
        storage.write_asset(asset)
    except OSError as e:
        raise HTTPException(500, "The edited asset could not be saved") from e
    db.assets[asset_id] = asset
    return asset


@router.delete("/assets/{asset_id}", status_code=204)
def delete_asset(asset_id: str):
    """Delete a generated asset (from memory and disk).

    Args:
        asset_id: Id of the asset (path parameter).

    Raises:
        HTTPException: 404 when no asset has this id.
    """
    asset = db.assets.pop(asset_id, None)
    if asset is None:
        raise HTTPException(404, f"Asset '{asset_id}' not found")
    storage.delete_asset(asset)
