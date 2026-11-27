"""Campaign Builder (Phase 2): zero-shot campaign kits (3 personas, 5 posts, 1 blurb): create one, delete one."""

import re
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import check_sources, checked_optional, checked_text, llm_limits, owned_project
from app.campaign import kit
from app.core import state as db
from app.core import ad_images, links, usage
from app.core.config import LLM_MODEL
from app.core.llm import GenerationError
from app.core.schemas import Asset, CampaignPage, CampaignRequest, CampaignResponse, CampaignSummary
from app.db import records

router = APIRouter()


@router.post("/projects/{project_id}/campaigns", response_model=CampaignResponse, status_code=201,
             dependencies=[Depends(owned_project), Depends(llm_limits)])
def create_campaign(project_id: str, body: CampaignRequest):
    """Generate a zero-shot campaign kit from a book brief: 3 personas, 5 social posts, 1 blurb.

    Runs the LangGraph in kit.py (personas first, then posts and blurb aimed at them). Each
    piece is stored as an ordinary Asset with the same campaign_id, so it can be copied, edited and
    deleted like any other asset. With a source_id, the assets belong to that book.

    Args:
        project_id: Id of the project (path parameter). 404 if unknown.
        body: The book brief.

    Returns:
        The kit's stored assets and the tokens it used.

    Raises:
        HTTPException: 400 if a field is a likely prompt injection; 404 if the project or the given book is
            unknown; 422 if a field is empty, too long or there are more than MAX_THEMES themes; 429 if the
            rate limit is reached; 503 if no API key is configured; 502 if a model call fails; 504 if it timed
            out after all retries; 500 if the assets cannot be saved.
    """
    check_sources(project_id, [body.source_id] if body.source_id else None)
    body = _checked_brief(body)
    campaign_id = db.new_id("cmp")
    try:
        with usage.tagged(campaign_id=campaign_id, source_id=body.source_id):  # its calls count for the kit and book
            result = kit.generate_campaign(body)
    except GenerationError as e:
        raise HTTPException(e.status_code, str(e)) from e

    brief = kit.format_brief(body)
    created = db.now()
    order = iter(range(9))  # 1 µs apart, so the kit keeps its order when the assets are reloaded (sorted by time)

    project = db.projects.get(project_id)
    own = links.own_links(project.owner_id if project else None)

    def make(asset_type, text: str, tokens: int, **extra) -> Asset:
        """One asset of the kit with the fields all pieces share; only the author's book links stay in its text."""
        text, _ = links.keep_own_links(text, own)
        return Asset(id=db.new_id("ast"), project_id=project_id, asset_type=asset_type, grounded=False, brief=brief,
                     text=text, citations=[], created_at=created + timedelta(microseconds=next(order)), tokens=tokens, audience=body.audience,
                     humanize=body.humanize, source_ids=[body.source_id] if body.source_id else [],
                     campaign_id=campaign_id, model=LLM_MODEL, prompt_version=kit.PROMPT_VERSION, **extra)

    # Each step's tokens go to its first asset, so the project's token count still adds up.
    personas = [make("persona", kit.format_persona(p), result["persona_tokens"] if i == 0 else 0)
                for i, p in enumerate(result["personas"])]
    posts = [make("social_post", piece["text"], piece["tokens"] + (result["posts_tokens"] if i == 0 else 0),
                  platform=post.platform, persona=post.persona, angle=post.angle, ai_tells=piece["ai_tells"])
             for i, (post, piece) in enumerate(zip(result["posts"], result["polished_posts"]))]
    piece = result["polished_blurb"]
    blurb = make("blurb", piece["text"], piece["tokens"] + result["blurb_tokens"], ai_tells=piece["ai_tells"])

    kit_assets = [*personas, *posts, blurb]
    try:
        records.save_assets(kit_assets)  # one transaction: the whole kit is saved, or none of it
    except OSError as e:  # DatabaseError
        raise HTTPException(500, "The campaign was generated but could not be saved") from e
    db.assets.update((asset.id, asset) for asset in kit_assets)
    return CampaignResponse(campaign_id=campaign_id, personas=personas, posts=posts, blurb=blurb,
                            tokens=result.get("tokens", 0))


@router.get("/projects/{project_id}/campaigns", response_model=CampaignPage, dependencies=[Depends(owned_project)])
def list_campaigns(project_id: str, limit: int = Query(10, ge=1, le=100), offset: int = Query(0, ge=0)):
    """One page of the project's campaign kits, newest first: one summary row each, without the assets' texts,
    so the list stays small with many kits (GET .../campaigns/{campaign_id} loads one kit's assets).

    Args:
        project_id: Id of the project (path parameter). 404 if unknown or not the user's.
        limit: Kits per page (1-100).
        offset: Kits to skip (the newest first).
    """
    kits: dict[str, list[Asset]] = {}
    for asset in db.assets.values():
        if asset.project_id == project_id and asset.campaign_id:
            kits.setdefault(asset.campaign_id, []).append(asset)
    rows = sorted((_summary(cid, assets) for cid, assets in kits.items()), key=lambda r: r.created_at, reverse=True)
    page = rows[offset:offset + limit]
    try:
        costs = records.campaign_costs(r.campaign_id for r in page)
    except OSError:  # DatabaseError: the list still works, only without costs
        costs = {}
    return CampaignPage(items=[r.model_copy(update={"cost": costs.get(r.campaign_id)}) for r in page], total=len(rows))


@router.get("/projects/{project_id}/campaigns/{campaign_id}", response_model=list[Asset],
            dependencies=[Depends(owned_project)])
def get_campaign(project_id: str, campaign_id: str):
    """The assets of one campaign kit in the order they were made (personas, posts, blurb).

    Raises:
        HTTPException: 404 if the project has no asset of this campaign.
    """
    assets = _kit(project_id, campaign_id)
    if not assets:
        raise HTTPException(404, f"Campaign '{campaign_id}' not found")
    return assets


@router.delete("/projects/{project_id}/campaigns/{campaign_id}", status_code=204, dependencies=[Depends(owned_project)])
def delete_campaign(project_id: str, campaign_id: str):
    """Delete a whole campaign kit: every asset of the project with this campaign_id, in one transaction.

    Args:
        project_id: Id of the project (path parameter). 404 if unknown or not the user's.
        campaign_id: Id of the campaign (path parameter), e.g. "cmp_1a2b3c4d".

    Raises:
        HTTPException: 404 if the project has no asset of this campaign; 500 if they cannot be deleted
            (then all of them are kept).
    """
    ids = [a.id for a in _kit(project_id, campaign_id)]
    if not ids:
        raise HTTPException(404, f"Campaign '{campaign_id}' not found")
    pictures = ad_images.paths_of(ids)
    try:
        records.delete_assets(ids)
    except OSError as e:  # DatabaseError
        raise HTTPException(500, "The campaign could not be deleted, please try again.") from e
    ad_images.delete_files(pictures)
    for asset_id in ids:
        db.assets.pop(asset_id, None)


def _kit(project_id: str, campaign_id: str) -> list[Asset]:
    """The project's assets of this campaign, oldest first ([] for an unknown campaign)."""
    return sorted((a for a in db.assets.values() if a.project_id == project_id and a.campaign_id == campaign_id),
                  key=lambda a: a.created_at)


def _summary(campaign_id: str, assets: list[Asset]) -> CampaignSummary:
    """The list row of one kit; its title comes from the brief's first line ('Book: "Title" by Author')."""
    first = min(assets, key=lambda a: a.created_at)
    title = re.match(r'Book: "([^"]+)"', first.brief)
    return CampaignSummary(campaign_id=campaign_id, title=title.group(1) if title else "Campaign",
                           source_id=first.source_ids[0] if first.source_ids else None, created_at=first.created_at,
                           tokens=sum(a.tokens for a in assets), asset_count=len(assets), audience=first.audience)


MAX_THEMES = 10


def _checked_brief(body: CampaignRequest) -> CampaignRequest:
    """The brief with every text field cleaned and checked (deps.checked_text): all of it is the user's own
    instruction to the model, so likely prompt injections are blocked.

    Raises:
        HTTPException: 400, 422 (see create_campaign).
    """
    if len(body.themes) > MAX_THEMES:
        raise HTTPException(422, f"themes: at most {MAX_THEMES} themes are allowed.")
    return body.model_copy(update={
        "title": checked_text(body.title, "short_text", "title"),
        "author": checked_optional(body.author, "short_text", "author"),
        "genre": checked_optional(body.genre, "short_text", "genre"),
        "themes": [t for t in (checked_optional(t, "short_text", "theme") for t in body.themes) if t],
        "premise": checked_text(body.premise, "brief", "premise"),
        "comparables": checked_optional(body.comparables, "short_text", "comparables"),
        "audience": checked_optional(body.audience, "short_text", "audience"),
    })
