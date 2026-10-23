"""Campaign Builder (Phase 2): zero-shot campaign kits (3 personas, 5 posts, 1 blurb)."""

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import checked_optional, checked_text, get_project_or_404, get_source_or_404, llm_rate_limit
from app.campaign import kit
from app.core import state as db
from app.core import storage
from app.core.llm import GenerationError
from app.core.schemas import Asset, CampaignRequest, CampaignResponse

router = APIRouter()


@router.post("/projects/{project_id}/campaigns", response_model=CampaignResponse, status_code=201,
             dependencies=[Depends(llm_rate_limit)])
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
            rate limit is reached; 503 if no API key is configured; 502 if a model call fails; 500 if the
            assets cannot be saved.
    """
    get_project_or_404(project_id)
    if body.source_id:
        get_source_or_404(body.source_id)
    body = _checked_brief(body)
    try:
        result = kit.generate_campaign(body)
    except GenerationError as e:
        raise HTTPException(e.status_code, str(e)) from e

    campaign_id = db.new_id("cmp")
    brief = kit.format_brief(body)
    created = db.now()
    order = iter(range(9))  # 1 µs apart, so the kit keeps its order when the assets are reloaded (sorted by time)

    def make(asset_type, text: str, tokens: int, **extra) -> Asset:
        """One asset of the kit with the fields all pieces share."""
        return Asset(id=db.new_id("ast"), project_id=project_id, asset_type=asset_type, grounded=False, brief=brief,
                     text=text, citations=[], created_at=created + timedelta(microseconds=next(order)), tokens=tokens, audience=body.audience,
                     humanize=body.humanize, source_ids=[body.source_id] if body.source_id else [],
                     campaign_id=campaign_id, **extra)

    # Each step's tokens go to its first asset, so the project's token count still adds up.
    personas = [make("persona", kit.format_persona(p), result["persona_tokens"] if i == 0 else 0)
                for i, p in enumerate(result["personas"])]
    posts = [make("social_post", piece["text"], piece["tokens"] + (result["posts_tokens"] if i == 0 else 0),
                  platform=post.platform, persona=post.persona, angle=post.angle, ai_tells=piece["ai_tells"])
             for i, (post, piece) in enumerate(zip(result["posts"], result["polished_posts"]))]
    piece = result["polished_blurb"]
    blurb = make("blurb", piece["text"], piece["tokens"] + result["blurb_tokens"], ai_tells=piece["ai_tells"])

    try:
        for asset in [*personas, *posts, blurb]:
            storage.write_asset(asset)
            db.assets[asset.id] = asset
    except OSError as e:
        raise HTTPException(500, "The campaign was generated but could not be saved") from e
    return CampaignResponse(campaign_id=campaign_id, personas=personas, posts=posts, blurb=blurb,
                            tokens=result.get("tokens", 0))


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
