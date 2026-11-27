"""Engagement agent (human in the loop), phase 2 of the marketing agent's cycle: when no reader commented, start a
discussion under one of the author's own recent Facebook Page posts or YouTube videos that has no comments yet, with
one inviting question drafted from the books, posted only after the author's "make it so" in Telegram.

    START ─► draft ─► propose ─► wait ⏸ ─(make it so)─► publish ─► END
                         ▲          │
                         │          ├─(skip)───────────► skip ────► END
                         ├─ revise ◄┤(feedback)
                         └─ use_text ◄┘(edit: the author's own text, used as it is; no model call)

    pick_post    Facebook: the newest own post (from_page) of the last `engage_days` with no comments and text
    pick_video   YouTube: an own upload of the last `youtube_engage_days` (comments not turned off), on the channel
                 the inbox owner connected (page_inbox.channel_for_inbox): the newest without comments, else the newest
                 whose last comment is QUIET_DAYS old (another question, so the video does not look dead; its latest
                 comments go to the prompt so the question is new). No limit per video: the daily limit keeps the pace
                 Rotation: among the videos that fit, one never proposed comes first (newest first), then the one
                 proposed longest ago, so a skipped video goes to the back of the line.
                 Both: not while a proposal for it waits; a skipped one comes back after SKIP_RETRY; a post with any
                 other outcome counts for good, a video for QUIET_DAYS
    draft        the book whose passages fit the post (a video: its title, description and transcript) best (one
                 vector search per book), its best passages, and one model call (prompts/engagement_comment.md): one
                 open question, at most 3 sentences, no promotion; or, with style "thought" (the schedule's
                 `youtube_engage`, YouTube's default; prompts/engagement_thought.md), a comment about one topic of the
                 video and what the book says about it, no question. A video's transcript is fetched once, for the first
                 draft (youtube.video_transcript, 250 quota units), and kept for revisions; without captions, or when
                 YouTube refuses them, the question is drawn from title and description
    propose      the post or video, the book, why, and the comment to Telegram with "Make it so" / "Skip"
    wait         interrupt(): stored by the checkpointer until the author answers (resume)
    revise       the same prompt again with the author's feedback and the current comment, from the same passages
    publish      the output guard once more, then facebook.comment_on_post as the Page, or youtube.comment_on_video as
                 the channel; Telegram gets the link

Like the Page inbox (page_inbox.py): one waiting proposal at a time across both agents (the worker asks both),
a decision is applied exactly once under a lock, MAX_REVISIONS feedback rounds, runs kept by the shared
checkpointer (agents/checkpoints.py), so a waiting proposal survives a server restart (restore()). Thread ids start with "eng:" so the worker knows which agent a run belongs to.
The post and the video's title, description and transcript are the author's own text; the feedback is the author's own instruction. Runs are traced as "engagement".
"""

import logging
import threading
from datetime import datetime, timedelta
from functools import cache
from typing import Literal, TypedDict
from zoneinfo import ZoneInfo

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from pydantic import BaseModel, Field

from app.agents import checkpoints
from app.agents import page_inbox as inbox
from app.core import prompt_files, prompts, tracing, usage
from app.core import state as db
from app.core.guard import clean_text, output_blocked, quote_untrusted
from app.core.llm import structured
from app.core.schemas import AutomationSettings, FacebookPost, YouTubeUpload
from app.core.style import style_guidance, temperature_for
from app.db import records
from app.rag.retrieval import format_context, retrieve_chunks, source_name
from app.social import facebook, telegram, youtube

logger = logging.getLogger(__name__)

PREFIX = "eng:"
HUMANIZE = inbox.HUMANIZE
MAX_REVISIONS = inbox.MAX_REVISIONS
SCAN_POSTS = 10  # latest posts looked at
SCAN_VIDEOS = 50  # latest uploads looked at (the most one read returns; still 3 quota units)
PASSAGES = 4  # book passages given to the model
POST_TEXT = 3000  # characters of the post given to the model (and of a video's text used for the book search)
VIDEO_TEXT = 9000  # characters of a video's title, description and transcript given to the model
EXCERPT = 300  # characters of the post shown in Telegram
LOG_CYCLES = 200  # cycles read to find the posts that had a proposal already
SKIP_RETRY = timedelta(days=1)  # a skipped post or video may get a question again after this
QUIET = timedelta(days=5)  # a video whose last comment is this old may get another question
MAX_QUIET_CHECKS = 10  # videos with comments whose last comment is read per pick (1 quota unit each)
EARLIER_COMMENTS = 5  # latest comments under a video given to the model with another question

PROMPT = prompt_files.chat_prompt("engagement_comment")  # prompts/engagement_comment.md
THOUGHT_PROMPT = prompt_files.chat_prompt("engagement_thought")  # prompts/engagement_thought.md

Outcome = Literal["posted", "skipped", "failed", "blocked", "gave_up", "tested"]
Platform = Literal["facebook", "youtube"]
Style = Literal["question", "thought"]  # what the comment is: one open question, or a thought from the book
Target = FacebookPost | YouTubeUpload  # what the question goes under

# How each platform reads in the prompt.
WHERE = {"facebook": "their own Facebook Page under one of their own recent posts",
         "youtube": "their own YouTube channel under one of their own videos"}
LABEL = {"facebook": "My post on my Facebook Page",
         "youtube": "My video on my YouTube channel (title, description and, if there is one, what is said in it)"}


class EngagementComment(BaseModel):
    """One comment that starts a discussion under the author's post."""

    comment: str = Field(min_length=1, max_length=800, description="The comment: at most 3 sentences, ending in one "
                                                                    "open question; [n] markers for passages used.")
    reason: str = Field(description="One sentence for the author: why this question fits the post and the book.")


class EngagementThought(BaseModel):
    """One comment under the author's video about a topic of it and what the book says about that (no question)."""

    comment: str = Field(min_length=1, max_length=1000, description="The comment: 2 to 4 sentences about one topic "
                                                                     "of the video and what the book says about it; "
                                                                     "no question; [n] markers for passages used.")
    reason: str = Field(description="One sentence for the author: which topic of the video this picks up and why "
                                    "the book fits it.")


PROMPT_VERSION = prompts.register("engagement", PROMPT, EngagementComment, THOUGHT_PROMPT, EngagementThought,
                                  {"humanize": HUMANIZE})
WRITERS = {"question": (PROMPT, EngagementComment), "thought": (THOUGHT_PROMPT, EngagementThought)}


class EngageState(TypedDict, total=False):
    post: dict  # the FacebookPost or YouTubeUpload (as JSON, for the checkpointer)
    platform: Platform  # missing in runs from before YouTube: facebook
    style: Style  # missing in runs from before the thought comments: question
    transcript: str  # a video's spoken text ("" = none), fetched for the first draft
    source_ids: list[str]
    source_id: str
    chunk_ids: list[str]  # the passages the comment is drawn from (kept for revisions)
    comment: str
    reason: str
    revisions: int
    proposal_message_id: int
    decision: str  # approve | skip | feedback | edit
    own_text: bool  # the comment is the author's own text (Edit), not a model's
    feedback: str
    outcome: Outcome
    posted_url: str
    test: bool  # test mode: nothing is posted
    humanize: int  # how human the question sounds (the schedule's humanize when the run started)


# ---------- choosing the post ----------
def candidates(posts: list[FacebookPost], days: int, done: set[str], now: datetime) -> list[FacebookPost]:
    """The posts a question may go under, newest first: the Page's own, with text, without comments, not older than
    `days`, and not tried before (`done`)."""
    since = now - timedelta(days=days)
    found = [p for p in posts if p.from_page and p.comment_count == 0 and p.message.strip()
             and p.created_time >= since and p.id not in done]
    return sorted(found, key=lambda p: p.created_time, reverse=True)


def video_candidates(videos: list[YouTubeUpload], days: int, done: set[str], now: datetime) -> list[YouTubeUpload]:
    """The videos a question may go under, newest first: no comments yet (comments not turned off), a title, not older
    than `days`, and not tried before (`done`)."""
    since = now - timedelta(days=days)
    found = [v for v in videos if v.comment_count == 0 and v.title.strip() and v.published_at >= since
             and v.id not in done]
    return sorted(found, key=lambda v: v.published_at, reverse=True)


def pick_video(settings: AutomationSettings) -> YouTubeUpload | None:
    """The video for this cycle's question, or None (also when no channel is connected).

    Raises:
        YouTubeError: If the channel cannot be read.
        DatabaseError: If the connection cannot be read.
    """
    channel = inbox.channel_for_inbox()
    if channel is None:
        return None
    now = db.now()
    proposals = _proposals(settings.user_id)
    tried = tried_posts(settings.user_id, again_after=QUIET, proposals=proposals)
    last = last_proposed(proposals)
    with youtube.as_channel(channel):
        videos = youtube.recent_videos(SCAN_VIDEOS)
        found = rotate(video_candidates(videos, settings.youtube_engage_days, tried, now), last)
        if found:
            return found[0]
        since = now - timedelta(days=settings.youtube_engage_days)
        commented = rotate([v for v in videos if v.comment_count and v.title.strip() and v.published_at >= since
                            and v.id not in tried], last)
        for video in commented[:MAX_QUIET_CHECKS]:
            try:
                comments = youtube.latest_comments(video.id, EARLIER_COMMENTS)
            except youtube.YouTubeError as e:  # e.g. comments turned off since
                logger.info("Engagement: comments of video %s not readable: %s", video.id, e)
                continue
            if not comments or now - comments[0].created_time >= QUIET:
                return video.model_copy(update={"earlier_comments": [c.message for c in comments if c.message]})
    return None


def pick_post(settings: AutomationSettings) -> FacebookPost | None:
    """The post for this cycle's question, or None.

    Raises:
        FacebookError: If the Page cannot be read.
    """
    posts = facebook.list_posts(limit=SCAN_POSTS).items
    found = candidates(posts, settings.engage_days, tried_posts(settings.user_id), db.now())
    return found[0] if found else None


def tried_posts(user_id: str, again_after: timedelta | None = None,
                proposals: list[tuple[str, datetime, bool]] | None = None) -> set[str]:
    """Posts and videos not to propose now: those with an engagement proposal (from the cycle log and this process),
    except the ones skipped longer than SKIP_RETRY ago and, with `again_after`, the ones decided otherwise longer than
    that ago (None: those count for good). `proposals`: from _proposals, if already read."""
    now = db.now()
    with _lock:
        waiting = set(_runs)
    found = _proposals(user_id) if proposals is None else proposals
    return waiting | {p for p, at, skipped in found if not _over(at, skipped, again_after, now)}


def last_proposed(proposals: list[tuple[str, datetime, bool]]) -> dict[str, datetime]:
    """When each post or video last had an engagement proposal (from _proposals)."""
    last: dict[str, datetime] = {}
    for post_id, at, _ in proposals:
        last[post_id] = max(at, last.get(post_id, at))
    return last


def rotate(videos: list[YouTubeUpload], last: dict[str, datetime]) -> list[YouTubeUpload]:
    """The videos in turn: never proposed first (newest first, as given), then the one proposed longest ago."""
    never = [v for v in videos if v.id not in last]
    return never + sorted((v for v in videos if v.id in last), key=lambda v: last[v.id])


def _proposals(user_id: str) -> list[tuple[str, datetime, bool]]:
    """Every decided engagement proposal: (post or video id, when, skipped), from the cycle log and this process."""
    with _lock:
        found = [(p, at, skipped) for p, (at, skipped) in _decided.items()]
    try:
        for cycle in records.list_cycles(user_id, LOG_CYCLES):
            found += [(e.item_id, e.decided_at or e.proposed_at, e.outcome == "skipped")
                      for e in cycle.entries if e.kind == "comment"]
    except OSError as e:  # DatabaseError: only this process's memory counts
        logger.warning("Engagement: the cycle log cannot be read: %s", e)
    return found


def _over(decided_at: datetime, skipped: bool, again_after: timedelta | None, now: datetime) -> bool:
    """True if a post or video decided at `decided_at` may get a proposal again."""
    wait = SKIP_RETRY if skipped else again_after
    return wait is not None and now - decided_at >= wait


def posted_today(user_id: str, timezone: str, platform: Platform = "facebook") -> int:
    """How many comments and posts the agent made on its own initiative today on one platform (in the user's time
    zone): what that platform's daily limit counts (Facebook: questions and book posts; YouTube: questions). Replies
    to readers do not count.

    Raises:
        DatabaseError: If the cycle log cannot be read.
    """
    zone = ZoneInfo(timezone)
    today = db.now().astimezone(zone).date()
    return sum(1 for cycle in records.list_cycles(user_id, LOG_CYCLES) for e in cycle.entries
               if e.kind in ("comment", "post") and e.platform == platform and e.outcome == "posted"
               and e.decided_at and e.decided_at.astimezone(zone).date() == today)


# ---------- runs ----------
def is_engagement(thread_id: str) -> bool:
    return thread_id.startswith(PREFIX)


def platform_of(target: Target) -> Platform:
    return "youtube" if isinstance(target, YouTubeUpload) else "facebook"


def start(post: Target, test: bool = False, humanize: int = HUMANIZE, style: Style = "question") -> str | None:
    """Draft the comment for the post or video, send the proposal to Telegram and wait. `test`: test mode, nothing is
    posted; `humanize`: how human the comment sounds (0-100); `style`: one open question, or a thought (a topic of
    the video and what the book says about it, no question).

    Returns:
        The run's thread id, or None if it ended without waiting.

    Raises:
        InboxConfigError: If the books are not configured.
        GenerationError, TelegramError, DatabaseError: If drafting or sending fails (the post may be tried again).
    """
    _, source_ids = inbox.inbox_books()
    thread_id = f"{PREFIX}{post.id}:{db.new_id('run')}"
    with tracing.scope():
        _graph().invoke({"post": post.model_dump(mode="json"), "platform": platform_of(post), "source_ids": source_ids,
                         "revisions": 0, "test": test, "humanize": humanize, "style": style}, _config(thread_id))
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
        outcome = values.get("outcome", "gave_up")
        _decided[post_id] = (db.now(), outcome == "skipped")
        _runs.pop(post_id, None)
        return outcome


def restore() -> int:
    """On server start: the engagement runs kept in the database (see page_inbox.restore). A waiting run becomes the
    current proposal again; a finished run's post counts as tried.

    Returns:
        How many waiting runs were restored.
    """
    restored = 0
    with _lock:
        for thread_id in checkpoints.thread_ids(PREFIX):
            state = _graph().get_state(_config(thread_id))
            post_id = thread_id[len(PREFIX):].rsplit(":", 1)[0]
            if "wait" in state.next:
                _runs[post_id] = thread_id
                restored += 1
            elif state.next or checkpoints.is_old(state.created_at):  # broken off by an error, or old
                checkpoints.delete(thread_id)
            else:
                at = _moment(state.created_at) if state.created_at else db.now()
                _decided[post_id] = (at, state.values.get("outcome") == "skipped")
    return restored


def _moment(iso: str) -> datetime:
    """A checkpoint's ISO time, with a time zone."""
    moment = datetime.fromisoformat(iso)
    return moment if moment.tzinfo else moment.replace(tzinfo=ZoneInfo("UTC"))


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
_lock = threading.RLock()
_runs: dict[str, str] = {}  # post or video id → its run's thread id, while the run waits
_decided: dict[str, tuple[datetime, bool]] = {}  # posts and videos decided in this process → (when, skipped)


@cache
def _graph():
    builder = StateGraph(EngageState)
    builder.add_node("draft", _draft)
    builder.add_node("propose", _propose)
    builder.add_node("wait", _wait)
    builder.add_node("revise", _draft)  # the same writer, now with the feedback and the current comment
    builder.add_node("use_text", _use_text)
    builder.add_node("publish", _publish)
    builder.add_node("skip", _skip)
    builder.add_edge(START, "draft")
    builder.add_edge("draft", "propose")
    builder.add_edge("propose", "wait")
    builder.add_conditional_edges("wait", _after_wait, ["publish", "skip", "revise", "use_text", END])
    builder.add_edge("revise", "propose")
    builder.add_edge("use_text", "propose")
    builder.add_edge("publish", END)
    builder.add_edge("skip", END)
    return builder.compile(checkpointer=checkpoints.checkpointer())


def _draft(state: EngageState) -> EngageState:
    """Write the comment (first draft, or a rewrite following the author's feedback)."""
    platform = _platform(state)
    target = _target(state)
    feedback = state.get("feedback", "")
    update: EngageState = {}
    if state.get("chunk_ids"):  # a rewrite: the same passages (and the same transcript)
        transcript = state.get("transcript", "")
        text = clean_text(_text(target, transcript))
        source_id = state["source_id"]
        passages = [(db.chunks[c], 0.0) for c in state["chunk_ids"] if c in db.chunks]
    else:
        transcript = _transcript(target) if isinstance(target, YouTubeUpload) else ""
        text = clean_text(_text(target, transcript))
        source_id, passages = _best_book(state["source_ids"], text[:POST_TEXT])
        update = {"source_id": source_id, "chunk_ids": [chunk.id for chunk, _ in passages], "transcript": transcript}
    text = text[:VIDEO_TEXT if platform == "youtube" else POST_TEXT]
    prompt, schema = WRITERS[_style(state)]
    with usage.tagged(source_id=source_id):
        result, _ = structured(prompt, {
            "style": style_guidance(humanize := state.get("humanize", HUMANIZE)),
            "book": source_name(source_id) or source_id, "post": text,
            "where": WHERE[platform], "label": LABEL[platform], "earlier": _earlier(target),
            "context": format_context(passages) or "(no passages)",
            "current": facebook.publishable_text(state.get("comment", "")) or "(none yet)",
            "feedback": feedback or "(none)",
        }, schema, "engagement comment", temperature_for(humanize))
    update.update({"comment": result.comment, "reason": result.reason, "feedback": "", "own_text": False})
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
    target = _target(state)
    comment = facebook.publishable_text(state["comment"])
    blocked = bool(comment) and output_blocked(comment)
    if old := state.get("proposal_message_id"):
        inbox._quietly(telegram.remove_buttons, old)
    buttons = inbox.proposal_buttons(bool(comment) and not blocked, state.get("test", False))
    thought = _style(state) == "thought"
    if isinstance(target, YouTubeUpload):
        lines = [inbox.PLATFORM_TAG["youtube"],
                 ("💡 A comment under your video: one of its topics and what your book says about it" if thought
                  else "💡 A question to start a discussion under your video")
                 + (inbox.TEST_HEAD if state.get("test") else ""),
                 f"Your video ({target.published_at:%d %b}): {inbox._excerpt(target.title, EXCERPT)}", target.url,
                 "📝 Drawn from what is said in the video (transcript)" if state.get("transcript")
                 else "📝 No transcript (no captions, or YouTube refused them): drawn from title and description"]
    else:
        lines = [inbox.PLATFORM_TAG["facebook"],
                 ("💡 A comment under your post: one of its topics and what your book says about it" if thought
                  else "💡 No new comments, so here is a question to start a discussion under your post")
                 + (inbox.TEST_HEAD if state.get("test") else ""),
                 f"Your post ({target.created_time:%d %b}): {inbox._excerpt(target.message, EXCERPT)}"]
        if target.permalink_url:
            lines.append(target.permalink_url)
    lines += ["", f"📖 {source_name(state['source_id']) or state['source_id']}",
              f"Why: {facebook.publishable_text(state.get('reason', ''))}"]
    lines += inbox.revision_note(state)
    if blocked:
        lines += ["", "⚠️ The comment looks like it contains instructions to an AI and will not be posted. Answer "
                      "with feedback to rewrite it, ✏️ Edit to write it yourself, or skip."]
    else:
        lines += ["", "Your comment:" if state.get("own_text") else "Proposed comment:", comment, "",
                  f"Answer “make it so” to post it as your {_as(state)}, “skip”, write what to change, or ✏️ Edit "
                  "to write it yourself."]
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
    if decision == "edit":  # the author's own text: no limit, it costs no model call
        return "use_text"
    if state.get("revisions", 0) >= MAX_REVISIONS:
        inbox._quietly(telegram.remove_buttons, state["proposal_message_id"])
        inbox._quietly(telegram.send_message, f"That was {MAX_REVISIONS} rounds of changes; I leave this "
                                              f"{_thing(state)} alone. Write the comment yourself on "
                                              f"{_site(state)} if you like.")
        return END
    return "revise"


def _use_text(state: EngageState) -> EngageState:
    """The author's own text (after "Edit") becomes the comment as it is."""
    return {"comment": state["feedback"].strip(), "own_text": True, "feedback": ""}


def current_text(thread_id: str) -> str:
    """The comment a run proposes now, as it would be posted."""
    return facebook.publishable_text(_graph().get_state(_config(thread_id)).values.get("comment", ""))


def _publish(state: EngageState) -> EngageState:
    """Post the comment as the Page under the post, or as the channel under the video."""
    target = _target(state)
    inbox._quietly(telegram.remove_buttons, state["proposal_message_id"])
    text = facebook.publishable_text(state["comment"])
    if not text or output_blocked(text):
        inbox._quietly(telegram.send_message, "Not posted: the comment is empty or looks like it contains "
                                              "instructions to an AI.")
        return {"outcome": "blocked"}
    if state.get("test"):
        inbox._quietly(telegram.send_message, inbox.TEST_NOT_POSTED)
        return {"outcome": "tested"}
    try:
        if isinstance(target, YouTubeUpload):
            channel = inbox.channel_for_inbox()
            if channel is None:
                raise youtube.YouTubeError(503, "your YouTube channel is no longer connected: connect it again in the "
                                                "app (Integrations → YouTube channel).")
            with youtube.as_channel(channel):
                posted = youtube.comment_on_video(target.id, text)
        else:
            posted = facebook.comment_on_post(target.id, text)
    except (facebook.FacebookError, youtube.YouTubeError, ValueError, OSError) as e:
        logger.warning("Engagement: posting the comment under %s failed: %s", target.id, e)
        inbox._quietly(telegram.send_message, f"Not posted, {_site(state)} said: {e}")
        return {"outcome": "failed"}
    link = posted.url or (target.url if isinstance(target, YouTubeUpload) else target.permalink_url) or ""
    where = "under your video" if isinstance(target, YouTubeUpload) else "on your Page"
    inbox._quietly(telegram.send_message, f"Posted {where}: {link}")
    return {"outcome": "posted", "posted_url": posted.url or ""}


def _skip(state: EngageState) -> EngageState:
    inbox._quietly(telegram.remove_buttons, state["proposal_message_id"])
    inbox._quietly(telegram.send_message, f"Skipped. Nothing was posted; I will not ask about this {_thing(state)} "
                                          "again.")
    return {"outcome": "skipped"}


def _config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}, "run_name": "engagement", "tags": ["engagement", "agent"],
            "metadata": {"operation": "engagement", "prompt_version": PROMPT_VERSION}}


def _waiting(thread_id: str) -> bool:
    return bool(_graph().get_state(_config(thread_id)).next)


def _platform(state: EngageState) -> Platform:
    return state.get("platform", "facebook")


def _style(state: EngageState) -> Style:
    return state.get("style", "question")


def _target(state: EngageState) -> Target:
    """The run's post or video, as its model."""
    model = YouTubeUpload if _platform(state) == "youtube" else FacebookPost
    return model.model_validate(state["post"])


def _text(target: Target, transcript: str = "") -> str:
    """What the question is drawn from: the post's text, or the video's title, description and transcript."""
    if isinstance(target, YouTubeUpload):
        text = f"Title: {target.title}\n\nDescription: {target.description}".strip()
        return f"{text}\n\nWhat is said in the video (transcript):\n{transcript}" if transcript else text
    return target.message


def _earlier(target: Target) -> str:
    """The comments already under a video that gets another question, quoted as outside text; "(none)" else."""
    comments = getattr(target, "earlier_comments", None) or []
    return "\n".join(quote_untrusted(c[:500], "post", n=i) for i, c in enumerate(comments, 1)) or "(none)"


def _transcript(video: YouTubeUpload) -> str:
    """The video's transcript, or "" when it has none or it cannot be fetched (the question is then drawn from title
    and description; logged, never an error)."""
    try:
        channel = inbox.channel_for_inbox()
        if channel is None:
            return ""
        with youtube.as_channel(channel):
            return youtube.video_transcript(video.id)
    except (youtube.YouTubeError, ValueError, OSError) as e:
        logger.info("Engagement: no transcript for video %s: %s", video.id, e)
        return ""


def _thing(state: EngageState) -> str:
    return "video" if _platform(state) == "youtube" else "post"


def _site(state: EngageState) -> str:
    return "YouTube" if _platform(state) == "youtube" else "Facebook"


def _as(state: EngageState) -> str:
    return "channel" if _platform(state) == "youtube" else "Page"
