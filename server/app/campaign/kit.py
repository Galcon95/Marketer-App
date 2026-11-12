"""Zero-shot campaign kit with LangGraph: one book brief → 3 reader personas, 5 social posts, 1 blurb.

    START ─► personas ─┬─► posts ─┬─► polish ─► END
                       └─► blurb ─┘

    personas  the brief → 3 reader personas (structured output): who they are, what they read,
              why this book appeals to them, where to reach them, a message that works
    posts     brief + personas → 5 posts, each written for one persona on a platform where that
              persona is reached, in five angles (hook, teaser, question, behind the scenes, call to action)
    blurb     brief + personas → a back-cover / store description aimed at the strongest persona
    polish    finds AI-typical clichés in posts and blurb (core/style.find_ai_tells); from humanize 60 on
              the humanizer rewrites every post once, the blurb when clichés were found (core/style.REWRITE_PROMPT)

posts and blurb run in parallel, both after personas, so the whole kit targets the same readers.
Zero-shot: the model sees only the brief, never excerpts from the book, so nothing is cited. The
Knowledge Hub's grounded generator is the counterpart that writes from the book's text. Runs are
traced in LangSmith as "generate_campaign" when tracing is on. The prompts are Markdown files:
prompts/campaign_personas.md, campaign_audience.md, campaign_posts.md and campaign_blurb.md.
"""

import logging
import operator
from functools import cache
from typing import Annotated, Literal, TypedDict

from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field, model_validator

from app.core import prompt_files
from app.core import prompts, style, tracing
from app.core.config import LLM_MODEL
from app.core.logs import current_request_id
from app.core.llm import GenerationError, chat_model, is_configured, model_failure, structured, tokens_used
from app.core.schemas import CampaignRequest, Platform
from app.core.style import (
    PLATFORM_POST, REWRITE_PROMPT, find_ai_tells, should_rewrite, style_guidance, tells_for_prompt, temperature_for,
)

logger = logging.getLogger(__name__)

# The five post angles, one post each, in this order.
ANGLES = ["hook", "teaser", "question", "behind the scenes", "call to action"]

PERSONAS_PROMPT = prompt_files.chat_prompt("campaign_personas")  # prompts/campaign_personas.md

POSTS_PROMPT = prompt_files.chat_prompt("campaign_posts")  # prompts/campaign_posts.md

BLURB_PROMPT = prompt_files.chat_prompt("campaign_blurb")  # prompts/campaign_blurb.md


class Persona(BaseModel):
    """One reader persona (structured output of the personas step)."""

    name: str = Field(description="A first name plus a short label, at most 6 words, e.g. 'Maria, the weekend binge-reader'.")
    snapshot: str = Field(description="One sentence: who they are (age range, life situation).")
    reads: str = Field(description="What they read now: genres, kinds of books or authors.")
    why_this_book: str = Field(description="Why this book appeals to them, in 1-2 sentences.")
    platforms: list[Platform] = Field(description="1-3 social platforms where they are best reached.")
    message: str = Field(description="One sentence: the message that would make them buy it.")


class PersonaSet(BaseModel):
    """Structured output of the personas step."""

    personas: list[Persona] = Field(min_length=3, max_length=3, description="Exactly three distinct reader personas.")


class Post(BaseModel):
    """One social post of the kit (structured output of the posts step)."""

    angle: Literal["hook", "teaser", "question", "behind the scenes", "call to action"]
    persona: str = Field(description="Name of the persona this post is written for, exactly as given.")
    platform: Platform = Field(description="Platform of the post: one where this persona is reached.")
    text: str = Field(description="The post text, ready to publish, following the platform's rules.")


class PostSet(BaseModel):
    """Structured output of the posts step."""

    posts: list[Post] = Field(min_length=5, max_length=5, description="Exactly five posts, one per angle, in the given order.")

    @model_validator(mode="after")
    def _one_post_per_angle(self) -> "PostSet":
        """Each angle exactly once; the posts are put into ANGLES order (a mere reordering is no reason to fail)."""
        if sorted(p.angle for p in self.posts) != sorted(ANGLES):
            raise ValueError(f"need exactly one post per angle {ANGLES}, got {[p.angle for p in self.posts]}")
        self.posts.sort(key=lambda p: ANGLES.index(p.angle))
        return self


class Piece(TypedDict):
    """A finished post or blurb after polishing: final text, clichés left, tokens of its rewrite (0 if none)."""

    text: str
    ai_tells: list[str]
    tokens: int


class CampaignState(TypedDict, total=False):
    """State passed through the graph. Input: req. The steps add personas, posts, blurb and token counts;
    polish adds the final texts (polished_posts, polished_blurb)."""

    req: CampaignRequest
    personas: list[Persona]
    posts: list[Post]
    blurb: str
    persona_tokens: int  # tokens of the personas call
    posts_tokens: int  # tokens of the posts call
    blurb_tokens: int  # tokens of the blurb call
    polished_posts: list[Piece]  # same order as posts
    polished_blurb: Piece
    tokens: Annotated[int, operator.add]  # all tokens of the kit (summed over the parallel steps)


# Version of this feature's prompts, e.g. "campaign@3f9a1c2e"; changes by itself when a prompt changes (core/prompts.py).
PROMPT_VERSION = prompts.register("campaign", PERSONAS_PROMPT, POSTS_PROMPT, BLURB_PROMPT, PersonaSet, PostSet,
                                 REWRITE_PROMPT, style.PLATFORM_POST, style.HUMAN_LEVELS, style.AI_TELLS)


# ---------- Public API ----------
def generate_campaign(req: CampaignRequest) -> CampaignState:
    """Run the campaign graph for one brief.

    Args:
        req: The book brief (title, author, genre, themes, premise, comparables, audience focus, humanize).

    Returns:
        The final state; use "personas", "posts" with "polished_posts" (same order), "polished_blurb",
        the per-step token counts and "tokens" (all tokens of the kit).

    Raises:
        GenerationError: 503 if no API key is configured, 502 if a model call fails or returns no usable result,
            504 if the provider timed out after all retries.
    """
    if not is_configured():
        raise GenerationError(503, "No API key set. Add OPENROUTER_API_KEY (or OPENAI_API_KEY) and restart the server.")
    try:
        with tracing.scope():
            return _graph().invoke(
                {"req": req},
                config={"run_name": "generate_campaign", "tags": ["zero-shot", "campaign"],
                        "metadata": {"request_id": current_request_id(), "prompt_version": PROMPT_VERSION,
                                     "llm_model": LLM_MODEL, "operation": "generate_campaign", "source_id": req.source_id}},
            )
    except GenerationError:
        raise
    except Exception as e:
        logger.exception("Campaign generation failed")
        raise model_failure(e) from e


def format_brief(req: CampaignRequest) -> str:
    """The brief as the human message, e.g. 'Book: "Garden Cities" by Ebenezer Howard\\nGenre: ...'; empty fields are left out."""
    book = f'Book: "{req.title.strip()}"' + (f" by {req.author.strip()}" if req.author.strip() else "")
    lines = [
        book,
        req.genre.strip() and f"Genre: {req.genre.strip()}",
        req.themes and f"Themes: {', '.join(t.strip() for t in req.themes if t.strip())}",
        f"Premise: {req.premise.strip()}",
        req.comparables.strip() and f"For fans of: {req.comparables.strip()}",
    ]
    return "\n".join(line for line in lines if line)


def format_persona(p: Persona) -> str:
    """Readable persona text for its asset: name and snapshot, then what they read, why, where and the message."""
    return (f"{p.name} — {p.snapshot}\n\nReads: {p.reads}\nWhy this book: {p.why_this_book}\n"
            f"Where to reach them: {', '.join(p.platforms)}\nMessage that works: {p.message}")


# ---------- Graph ----------
@cache
def _graph():
    """Build and compile the LangGraph: START → personas → (posts ∥ blurb) → polish → END."""
    builder = StateGraph(CampaignState)
    builder.add_node("personas", _personas)
    builder.add_node("posts", _posts)
    builder.add_node("blurb", _blurb)
    builder.add_node("polish", _polish)
    builder.add_edge(START, "personas")
    builder.add_edge("personas", "posts")
    builder.add_edge("personas", "blurb")
    builder.add_edge(["posts", "blurb"], "polish")  # waits for both branches
    builder.add_edge("polish", END)
    return builder.compile()


def _personas(state: CampaignState) -> CampaignState:
    """Personas node: the brief → three reader personas (structured output)."""
    req = state["req"]
    audience = (" " + prompt_files.text("campaign_audience").format(audience=req.audience.strip())  # prompts/campaign_audience.md
                if req.audience.strip() else "")
    parsed, tokens = structured(PERSONAS_PROMPT, {"brief": format_brief(req), "audience": audience}, PersonaSet,
                                "reader personas")
    return {"personas": parsed.personas, "persona_tokens": tokens, "tokens": tokens}


def _posts(state: CampaignState) -> CampaignState:
    """Posts node: brief + personas → five posts, one per angle, each for one persona on one of its platforms."""
    req = state["req"]
    rules = "\n".join(f"- {platform}: {rule}" for platform, rule in PLATFORM_POST.items())
    parsed, tokens = structured(
        POSTS_PROMPT, {"brief": format_brief(req), "personas": _persona_list(state["personas"]), "platform_rules": rules,
                       "style": style_guidance(req.humanize)},
        PostSet, "campaign posts", temperature=temperature_for(req.humanize))
    return {"posts": parsed.posts, "posts_tokens": tokens, "tokens": tokens}


def _blurb(state: CampaignState) -> CampaignState:
    """Blurb node: brief + personas → one back-cover / store description."""
    req = state["req"]
    reply: AIMessage = (BLURB_PROMPT | chat_model(temperature_for(req.humanize))).invoke(
        {"brief": format_brief(req), "personas": _persona_list(state["personas"]), "style": style_guidance(req.humanize)})
    tokens = tokens_used(reply)
    return {"blurb": str(reply.content).strip(), "blurb_tokens": tokens, "tokens": tokens}


def _polish(state: CampaignState) -> CampaignState:
    """Polish node: check posts and blurb for AI clichés; from humanize 60 on, the humanizer rewrites every post
    once, and the blurb when clichés were found."""
    humanize = state["req"].humanize
    posts = [_polish_text(p.text, humanize, emojis_expected=p.platform in ("instagram", "tiktok"), is_post=True)
             for p in state["posts"]]
    blurb = _polish_text(state["blurb"], humanize)
    return {"polished_posts": posts, "polished_blurb": blurb,
            "tokens": sum(p["tokens"] for p in posts) + blurb["tokens"]}


def _polish_text(text: str, humanize: int, emojis_expected: bool = False, is_post: bool = False) -> Piece:
    """One text through the cliché check and, if needed, one rewrite (as in generation.py's check_style/rewrite;
    posts always from humanize REWRITE_FROM on, see style.should_rewrite)."""
    tells = find_ai_tells(text, emojis_expected)
    if not should_rewrite(tells, humanize, is_post):
        return {"text": text, "ai_tells": tells, "tokens": 0}
    reply: AIMessage = (REWRITE_PROMPT | chat_model(temperature_for(humanize))).invoke({
        "tells": tells_for_prompt(tells), "style": style_guidance(humanize), "text": text,
    })
    new_text = str(reply.content).strip() or text
    return {"text": new_text, "ai_tells": find_ai_tells(new_text, emojis_expected), "tokens": tokens_used(reply)}


def _persona_list(personas: list[Persona]) -> str:
    """The personas for the posts and blurb prompts, one block each."""
    return "\n\n".join(format_persona(p) for p in personas)
