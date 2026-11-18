"""Engagement agent (human in the loop), phase 2 of the marketing agent's cycle: when no reader commented, start a
discussion under one of the author's own recent Facebook Page posts that has no comments yet, with one inviting
question drafted from the books, posted only after the author's "make it so" in Telegram.

    START ─► draft ─► propose ─► wait ⏸ ─(make it so)─► publish ─► END
                         ▲          │
                         │          ├─(skip)───────────► skip ────► END
                         └─ revise ◄┘(feedback)

    pick_post    the newest own post (from_page) of the last `engage_days` with no comments and text, that never had
                 an engagement proposal (any outcome: one try per post; from the cycle log, and in memory)
    draft        the book whose passages fit the post best (one vector search per book), its best passages, and one
                 model call (prompts/engagement_comment.md): one open question, at most 3 sentences, no promotion
    propose      the post, the book, why, and the comment to Telegram with "Make it so" / "Skip"
    wait         interrupt(): stored by the checkpointer until the author answers (resume)
    revise       the same prompt again with the author's feedback and the current comment, from the same passages
    publish      the output guard once more, then facebook.comment_on_post as the Page; Telegram gets the link

Like the Page inbox (page_inbox.py): one waiting proposal at a time across both agents (the worker asks both),
a decision is applied exactly once under a lock, MAX_REVISIONS feedback rounds, runs in memory (MemorySaver), so a
server restart drops a waiting proposal. Thread ids start with "eng:" so the worker knows which agent a run belongs to.
The post is the author's own text; the feedback is the author's own instruction. Runs are traced as "engagement".
"""

import logging
import threading
from datetime import datetime, timedelta
from functools import cache
from typing import Literal, TypedDict
from zoneinfo import ZoneInfo

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from pydantic import BaseModel, Field

from app.agents import page_inbox as inbox
from app.core import prompt_files, prompts, tracing, usage
from app.core import state as db
from app.core.guard import clean_text, output_blocked
from app.core.llm import structured
from app.core.schemas import AutomationSettings, FacebookPost, TelegramButton
from app.core.style import style_guidance, temperature_for
from app.db import records
from app.rag.retrieval import format_context, retrieve_chunks, source_name
from app.social import facebook, telegram

logger = logging.getLogger(__name__)

PREFIX = "eng:"
HUMANIZE = inbox.HUMANIZE
MAX_REVISIONS = inbox.MAX_REVISIONS
SCAN_POSTS = 10  # latest posts looked at
PASSAGES = 4  # book passages given to the model
POST_TEXT = 3000  # characters of the post given to the model
EXCERPT = 300  # characters of the post shown in Telegram
LOG_CYCLES = 200  # cycles read to find the posts that had a proposal already

PROMPT = prompt_files.chat_prompt("engagement_comment")  # prompts/engagement_comment.md

Outcome = Literal["posted", "skipped", "failed", "blocked", "gave_up"]


class EngagementComment(BaseModel):
    """One comment that starts a discussion under the author's post."""

    comment: str = Field(min_length=1, max_length=800, description="The comment: at most 3 sentences, ending in one "
                                                                    "open question; [n] markers for passages used.")
    reason: str = Field(description="One sentence for the author: why this question fits the post and the book.")


PROMPT_VERSION = prompts.register("engagement", PROMPT, EngagementComment, {"humanize": HUMANIZE})


class EngageState(TypedDict, total=False):
    post: dict  # the FacebookPost (as JSON, for the checkpointer)
    source_ids: list[str]
    source_id: str
    chunk_ids: list[str]  # the passages the comment is drawn from (kept for revisions)
    comment: str
    reason: str
    revisions: int
    proposal_message_id: int
    decision: str  # approve | skip | feedback
    feedback: str
    outcome: Outcome
    posted_url: str


# ---------- choosing the post ----------
def candidates(posts: list[FacebookPost], days: int, done: set[str], now: datetime) -> list[FacebookPost]:
    """The posts a question may go under, newest first: the Page's own, with text, without comments, not older than
    `days`, and not tried before (`done`)."""
    since = now - timedelta(days=days)
    found = [p for p in posts if p.from_page and p.comment_count == 0 and p.message.strip()
             and p.created_time >= since and p.id not in done]
    return sorted(found, key=lambda p: p.created_time, reverse=True)


def pick_post(settings: AutomationSettings) -> FacebookPost | None:
    """The post for this cycle's question, or None.

    Raises:
        FacebookError: If the Page cannot be read.
    """
    posts = facebook.list_posts(limit=SCAN_POSTS).items
    found = candidates(posts, settings.engage_days, tried_posts(settings.user_id), db.now())
    return found[0] if found else None


def tried_posts(user_id: str) -> set[str]:
    """Posts that had an engagement proposal already (any outcome), from the cycle log and this process."""
    with _lock:
        done = set(_decided) | {p for p in _runs}
    try:
        for cycle in records.list_cycles(user_id, LOG_CYCLES):
            done |= {e.item_id for e in cycle.entries if e.kind == "comment"}
    except OSError as e:  # DatabaseError: only this process's memory counts
        logger.warning("Engagement: the cycle log cannot be read: %s", e)
    return done


def posted_today(user_id: str, timezone: str) -> int:
    """How many comments and posts the agent made on its own initiative today (in the user's time zone): what the
    daily limit counts. Replies to readers do not count.

    Raises:
        DatabaseError: If the cycle log cannot be read.
    """
    zone = ZoneInfo(timezone)
    today = db.now().astimezone(zone).date()
    return sum(1 for cycle in records.list_cycles(user_id, LOG_CYCLES) for e in cycle.entries
               if e.kind in ("comment", "post") and e.outcome == "posted" and e.decided_at
               and e.decided_at.astimezone(zone).date() == today)


# ---------- runs ----------
def is_engagement(thread_id: str) -> bool:
    return thread_id.startswith(PREFIX)


def start(post: FacebookPost) -> str | None:
    """Draft the question for the post, send the proposal to Telegram and wait.

    Returns:
        The run's thread id, or None if it ended without waiting.

    Raises:
        InboxConfigError: If the books are not configured.
        GenerationError, TelegramError, DatabaseError: If drafting or sending fails (the post may be tried again).
    """
    _, source_ids = inbox.inbox_books()
    thread_id = f"{PREFIX}{post.id}:{db.new_id('run')}"
    with tracing.scope():
        _graph().invoke({"post": post.model_dump(mode="json"), "source_ids": source_ids, "revisions": 0},
                        _config(thread_id))
    if _waiting(thread_id):
        with _lock:
            _runs[post.id] = thread_id
        return thread_id
    return None


def resume(thread_id: str, message_id: int, decision: str, feedback: str = "") -> Outcome | Literal[
        "waiting", "stale"]:
    """Apply the author's answer to a waiting run exactly once (see page_inbox.resume)."""
    with _lock:
        state = _graph().get_state(_config(thread_id))
        if not _waiting(thread_id) or state.values.get("proposal_message_id") != message_id:
            return "stale"
        with tracing.scope():
            _graph().invoke(Command(resume={"decision": decision, "feedback": feedback}), _config(thread_id))
        if _waiting(thread_id):
            return "waiting"
        values = _graph().get_state(_config(thread_id)).values
        post_id = values["post"]["id"]
        _decided.add(post_id)
        _runs.pop(post_id, None)
        return values.get("outcome", "gave_up")


def waiting_run() -> tuple[str, int] | None:
    """The engagement run that waits for the author, with its proposal's message id, or None."""
    with _lock:
        for thread_id in list(_runs.values()):
            if _waiting(thread_id):
                return thread_id, _graph().get_state(_config(thread_id)).values["proposal_message_id"]
    return None


def posted_url(thread_id: str) -> str:
    """Where a finished run posted its comment ("" if it did not)."""
    return _graph().get_state(_config(thread_id)).values.get("posted_url", "") or ""


# ---------- Graph ----------
_checkpointer = MemorySaver()
_lock = threading.RLock()
_runs: dict[str, str] = {}  # post id → its run's thread id, while the run waits
_decided: set[str] = set()  # posts whose proposal was decided (in this process)


@cache
def _graph():
    builder = StateGraph(EngageState)
    builder.add_node("draft", _draft)
    builder.add_node("propose", _propose)
    builder.add_node("wait", _wait)
    builder.add_node("revise", _draft)  # the same writer, now with the feedback and the current comment
    builder.add_node("publish", _publish)
    builder.add_node("skip", _skip)
    builder.add_edge(START, "draft")
    builder.add_edge("draft", "propose")
    builder.add_edge("propose", "wait")
    builder.add_conditional_edges("wait", _after_wait, ["publish", "skip", "revise", END])
    builder.add_edge("revise", "propose")
    builder.add_edge("publish", END)
    builder.add_edge("skip", END)
    return builder.compile(checkpointer=_checkpointer)


def _draft(state: EngageState) -> EngageState:
    """Write the comment (first draft, or a rewrite following the author's feedback)."""
    post = FacebookPost.model_validate(state["post"])
    text = clean_text(post.message)[:POST_TEXT]
    feedback = state.get("feedback", "")
    update: EngageState = {}
    if state.get("chunk_ids"):  # a rewrite: the same passages
        source_id = state["source_id"]
        passages = [(db.chunks[c], 0.0) for c in state["chunk_ids"] if c in db.chunks]
    else:
        source_id, passages = _best_book(state["source_ids"], text)
        update = {"source_id": source_id, "chunk_ids": [chunk.id for chunk, _ in passages]}
    with usage.tagged(source_id=source_id):
        result, _ = structured(PROMPT, {
            "style": style_guidance(HUMANIZE), "book": source_name(source_id) or source_id, "post": text,
            "context": format_context(passages) or "(no passages)",
            "current": facebook.publishable_text(state.get("comment", "")) or "(none yet)",
            "feedback": feedback or "(none)",
        }, EngagementComment, "engagement comment", temperature_for(HUMANIZE))
    update.update({"comment": result.comment, "reason": result.reason, "feedback": ""})
    if feedback:
        update["revisions"] = state.get("revisions", 0) + 1
    return update


def _best_book(source_ids: list[str], text: str) -> tuple[str, list]:
    """The book whose best passage fits the post most, and its best passages."""
    project_id = db.sources[source_ids[0]].project_id
    best_id, best, best_score = source_ids[0], [], -1.0
    for sid in source_ids:
        found = retrieve_chunks(project_id, text, PASSAGES, [sid], operation="engagement")
        score = max((s for _, s in found), default=0.0)
        if score > best_score:
            best_id, best, best_score = sid, found, score
    return best_id, best


def _propose(state: EngageState) -> EngageState:
    """Send the proposal to Telegram; the buttons of an earlier proposal go."""
    post = FacebookPost.model_validate(state["post"])
    comment = facebook.publishable_text(state["comment"])
    blocked = bool(comment) and output_blocked(comment)
    if old := state.get("proposal_message_id"):
        inbox._quietly(telegram.remove_buttons, old)
    buttons = [TelegramButton(label="Skip", data=inbox.BUTTON_SKIP)]
    if comment and not blocked:
        buttons.insert(0, TelegramButton(label="✅ Make it so", data=inbox.BUTTON_GO))
    lines = ["💡 No new comments, so here is a question to start a discussion under your post",
             f"Your post ({post.created_time:%d %b}): {inbox._excerpt(post.message, EXCERPT)}"]
    if post.permalink_url:
        lines.append(post.permalink_url)
    lines += ["", f"📖 {source_name(state['source_id']) or state['source_id']}",
              f"Why: {facebook.publishable_text(state.get('reason', ''))}"]
    if state.get("revisions"):
        lines.append(f"(revised {state['revisions']}×)")
    if blocked:
        lines += ["", "⚠️ The comment looks like it contains instructions to an AI and will not be posted. Answer "
                      "with feedback to rewrite it, or skip."]
    else:
        lines += ["", "Proposed comment:", comment, "",
                  "Answer “make it so” to post it as your Page, “skip”, or write what to change."]
    return {"proposal_message_id": telegram.send_message("\n".join(lines), buttons=buttons)}


def _wait(state: EngageState) -> EngageState:
    """Stop until the author answers (runs twice: nothing else here)."""
    answer = interrupt({"proposal_message_id": state["proposal_message_id"]})
    return {"decision": answer["decision"], "feedback": answer.get("feedback", "")}


def _after_wait(state: EngageState) -> str:
    decision = state["decision"]
    if decision == "approve":
        return "publish"
    if decision in ("skip", "answered"):
        return "skip"
    if state.get("revisions", 0) >= MAX_REVISIONS:
        inbox._quietly(telegram.remove_buttons, state["proposal_message_id"])
        inbox._quietly(telegram.send_message, f"That was {MAX_REVISIONS} rounds of changes; I leave this post alone. "
                                              "Write the comment yourself on Facebook if you like.")
        return END
    return "revise"


def _publish(state: EngageState) -> EngageState:
    """Post the comment as the Page under the post."""
    post = FacebookPost.model_validate(state["post"])
    inbox._quietly(telegram.remove_buttons, state["proposal_message_id"])
    text = facebook.publishable_text(state["comment"])
    if not text or output_blocked(text):
        inbox._quietly(telegram.send_message, "Not posted: the comment is empty or looks like it contains "
                                              "instructions to an AI.")
        return {"outcome": "blocked"}
    try:
        posted = facebook.comment_on_post(post.id, text)
    except (facebook.FacebookError, ValueError) as e:
        logger.warning("Engagement: posting the comment under %s failed: %s", post.id, e)
        inbox._quietly(telegram.send_message, f"Not posted, Facebook said: {e}")
        return {"outcome": "failed"}
    inbox._quietly(telegram.send_message, f"Posted on your Page: {posted.url or post.permalink_url or ''}")
    return {"outcome": "posted", "posted_url": posted.url or ""}


def _skip(state: EngageState) -> EngageState:
    inbox._quietly(telegram.remove_buttons, state["proposal_message_id"])
    inbox._quietly(telegram.send_message, "Skipped. Nothing was posted; I will not ask about this post again.")
    return {"outcome": "skipped"}


def _config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}, "run_name": "engagement", "tags": ["engagement", "agent"],
            "metadata": {"operation": "engagement", "prompt_version": PROMPT_VERSION}}


def _waiting(thread_id: str) -> bool:
    return bool(_graph().get_state(_config(thread_id)).next)
