"""Generated assets: single-asset generation (grounded or zero-shot) and asset management."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.api.deps import check_sources, checked_optional, checked_text, llm_limits, owned_asset, owned_project
from app.core import export
from app.core import state as db
from app.core.llm import GenerationError
from app.core.schemas import Asset, AssetType, AssetUpdate, GenerateRequest
from app.db import records
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
        The newly created Asset, also saved in the database.

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
def list_assets(project_id: str, asset_type: AssetType | None = None, source_id: str | None = None,
                grounded: bool | None = None, in_campaign: bool | None = None,
                limit: int | None = Query(None, ge=1, le=1000)):
    """List the generated assets of a project, oldest first; every filter is optional.

    Args:
        project_id: Id of the project (path parameter). 404 if unknown.
        asset_type: Only this type, e.g. "persona".
        source_id: Only assets made for this book.
        grounded: Only grounded (true) or only zero-shot (false) assets.
        in_campaign: Only assets of campaign kits (true) or only those outside any kit (false).
        limit: At most this many, the newest (still listed oldest first).
    """
    assets = [a for a in db.assets.values() if a.project_id == project_id
              and (asset_type is None or a.asset_type == asset_type)
              and (source_id is None or source_id in a.source_ids)
              and (grounded is None or a.grounded == grounded)
              and (in_campaign is None or bool(a.campaign_id) == in_campaign)]
    return assets[-limit:] if limit else assets


@router.get("/projects/{project_id}/assets/export", dependencies=[Depends(owned_project)],
            responses={200: {"content": {"text/csv": {}, "text/markdown": {}}}})
def export_assets(project_id: str, format: Literal["csv", "csv_semicolon", "md"] = "csv",
                  asset_type: AssetType | None = None, source_id: str | None = None):
    """Download the project's assets as a file, newest first, optionally only one type and/or one book.

    Args:
        project_id: Id of the project (path parameter). 404 if unknown or not the user's.
        format: "csv" (comma: Google Sheets, scheduling tools), "csv_semicolon" (Excel with a German locale) or
            "md" (Markdown, to read and edit).
        asset_type: Only this type.
        source_id: Only assets made for this book.

    Raises:
        HTTPException: 404 if no asset matches.
    """
    assets = list(reversed(list_assets(project_id, asset_type=asset_type, source_id=source_id, limit=None)))
    if not assets:
        raise HTTPException(404, "No assets match these filters.")
    day = db.now().strftime("%Y-%m-%d")
    name = "-".join(p for p in ["assets", asset_type or "", day] if p).replace("_", "-")
    if format == "md":
        body = export.to_markdown(assets, title=f"Marketing assets ({export.TYPE_LABELS.get(asset_type, 'all types')})")
        media, name = "text/markdown; charset=utf-8", f"{name}.md"
    else:
        body = export.to_csv(assets, delimiter=";" if format == "csv_semicolon" else ",")
        media, name = "text/csv; charset=utf-8", f"{name}.csv"
    return Response(body, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"'})


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
        records.save_assets([asset])
    except OSError as e:  # DatabaseError
        raise HTTPException(500, "The edited asset could not be saved") from e
    db.assets[asset_id] = asset
    return asset


@router.delete("/assets/{asset_id}", status_code=204)
def delete_asset(asset: Asset = Depends(owned_asset)):
    """Delete a generated asset (from the database and memory).

    Args:
        asset_id: Id of the asset (path parameter).

    Raises:
        HTTPException: 404 when no asset of the user has this id; 500 if it cannot be deleted (it is then kept).
    """
    try:
        records.delete_assets([asset.id])
    except OSError as e:  # DatabaseError
        raise HTTPException(500, "The asset could not be deleted, please try again.") from e
    db.assets.pop(asset.id, None)
