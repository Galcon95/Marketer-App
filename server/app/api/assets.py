"""Generated assets: single-asset generation (grounded or zero-shot) and asset management."""

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import check_sources, checked_optional, checked_text, llm_limits, owned_asset, owned_project
from app.core import state as db
from app.core import storage
from app.core.llm import GenerationError
from app.core.schemas import Asset, AssetUpdate, GenerateRequest
from app.rag import generation

router = APIRouter()


# ---------- Generation & assets ----------
@router.post("/projects/{project_id}/generate", response_model=Asset, status_code=201,
             dependencies=[Depends(owned_project), Depends(llm_limits)])
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
        HTTPException: 400 if the brief or audience is a likely prompt injection; 404 for a book of the filter
            that is not in the project; 422 if a text is empty or too long; 429 if the rate limit is reached; 503 if no API key is configured; 502 if retrieval or the
            model call fails; 504 if the model timed out after all retries.
    """
    check_sources(project_id, body.source_ids)
    reply = body.asset_type == "social_reply"
    body = body.model_copy(update={
        # The user's own instructions to the model: checked for prompt injection.
        "brief": (checked_optional if reply else checked_text)(body.brief, "brief", "brief"),
        "audience": checked_optional(body.audience, "short_text", "audience"),
        # Someone else's post: never blocked (it is what the user answers), but only ever given to the model
        # as quoted data in a <post> block (generation.build_request).
        "reply_to": checked_optional(body.reply_to, "social_post", "post to reply to", check_injection=False),
    })
    try:
        return generation.create_asset(project_id, body)
    except GenerationError as e:
        raise HTTPException(e.status_code, str(e)) from e
    except OSError as e:
        raise HTTPException(500, "The asset was generated but could not be saved") from e


@router.get("/projects/{project_id}/assets", response_model=list[Asset], dependencies=[Depends(owned_project)])
def list_assets(project_id: str):
    """List all generated assets of a project.

    Args:
        project_id: Id of the project (path parameter). 404 if unknown.
    """
    return [a for a in db.assets.values() if a.project_id == project_id]


@router.get("/assets/{asset_id}", response_model=Asset)
def get_asset(asset: Asset = Depends(owned_asset)):
    """Return one generated asset. 404 when no asset of the user has this id."""
    return asset


@router.patch("/assets/{asset_id}", response_model=Asset)
def update_asset(asset_id: str, body: AssetUpdate, asset: Asset = Depends(owned_asset)):
    """Replace the text of a generated asset with the user's edited version (citations are kept).

    Args:
        asset_id: Id of the asset (path parameter).
        body: The new text.

    Raises:
        HTTPException: 404 when no asset of the user has this id; 422 if the text is empty or too long; 500 if it
            cannot be saved.
    """
    text = checked_text(body.text, "asset_text", "text", check_injection=False)  # the user's own edit, not a prompt
    asset = asset.model_copy(update={"text": text, "edited": True})
    try:
        storage.write_asset(asset)
    except OSError as e:
        raise HTTPException(500, "The edited asset could not be saved") from e
    db.assets[asset_id] = asset
    return asset


@router.delete("/assets/{asset_id}", status_code=204)
def delete_asset(asset: Asset = Depends(owned_asset)):
    """Delete a generated asset (from memory and disk).

    Args:
        asset_id: Id of the asset (path parameter).

    Raises:
        HTTPException: 404 when no asset of the user has this id.
    """
    db.assets.pop(asset.id, None)
    storage.delete_asset(asset)
