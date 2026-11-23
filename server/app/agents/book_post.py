"""Book post agent (human in the loop), phase 3 of the marketing agent's cycle: a new post on the author's Facebook
Page about the next topic of their books, with a call to action, published only after the author's "make it so" in
Telegram. Always newly written (never a post from Content Studio).

    START ─► draft ─► picture ─► propose ─► wait ⏸ ─(make it so)─► publish ─► END
                         ▲      ▲         ▲        │
                         │      │         │        ├─(skip)───────────► skip ────► END
                         │      │         └ no_picture ◄┤(without picture)
                         │      └── new_picture ◄───┤(new picture)
                         ├─ revise ◄────────────────┤(feedback)
                         └─ use_text ◄──────────────┘(edit: the author's own text, used as it is; no model call)

    next_topic   the topics are the chapters of the books' summaries (made in the app, Knowledge); the rotation takes
                 a topic never proposed before, the books taking turns (book 1 chapter 1, book 2 chapter 1, book 1
                 chapter 2, ...); when all were proposed, the one proposed longest ago. Proposed = any outcome, from the
                 cycle log (entries of kind "post", item_id "<source id>#<chapter index>") and this process's memory
    draft        the chapter's best passages (one vector search in that book), the latest own Page posts (not to
                 repeat them) and one model call (prompts/book_post.md): hook, one or two ideas, call to action
    picture      only with the schedule's `book_post_picture` (and pictures on, core/images.py): an ad picture for
                 the post, the book's cover in a scene, with a headline; headline and scene come from the post
                 (the same model call writes them). Stored at {project}/agent/{id}.png until the run ends. At most
                 MAX_PICTURES per run; a failed picture only adds a note (the post goes on without one)
    propose      the topic, the book, the post and its link to Telegram with "Make it so" / "Skip" (and the picture
                 above it, with "New picture" / "Without picture")
    wait         interrupt(): stored by the checkpointer until the author answers (resume)
    revise       the same prompt again with the author's feedback and the current post, from the same passages
    publish      the output guard once more, then facebook.publish_post (with the book link as its link preview),
                 or with a picture facebook.publish_photo (the link then at the end of the text);
                 in test mode nothing is published and Telegram says so (outcome "tested")

Like the other agents: one waiting proposal at a time across all agents, a decision is applied exactly once under a
lock, MAX_REVISIONS feedback rounds, runs kept by the shared checkpointer (agents/checkpoints.py), so a waiting
proposal survives a server restart (restore()). Thread ids start with "post:". Runs are traced as
"book_post".
"""

import logging
import threading
from datetime import datetime
from functools import cache
from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from pydantic import BaseModel, Field

from app.agents import checkpoints
from app.agents import page_inbox as inbox
from app.core import files, images, prompt_files, prompts, tracing, usage
from app.core import ad_images
from app.core import state as db
from app.core.guard import output_blocked, quote_untrusted
from app.core.llm import GenerationError, structured
from app.core.schemas import AutomationSettings, TelegramButton
from app.core.style import style_guidance, temperature_for
from app.db import records
from app.rag import ingestion
from app.rag.retrieval import format_context, retrieve_chunks, source_name
from app.social import facebook, telegram

logger = logging.getLogger(__name__)

PREFIX = "post:"
HUMANIZE = inbox.HUMANIZE
MAX_REVISIONS = inbox.MAX_REVISIONS
PASSAGES = 5  # book passages given to the model
RECENT_POSTS = 3  # latest own posts given to the model, not to repeat them
RECENT_TEXT = 600  # characters of each of them
LOG_CYCLES = 200  # cycles read for the rotation
MAX_PICTURES = 3  # pictures made per post (the first and two "new picture"), about $0.07 each
PICTURE_FORMAT = "square"  # 1:1, shown whole in the Facebook feed
# Chapters that make poor post topics (back matter the summary kept), by the start of their title.
NOT_TOPICS = ("appendix", "index", "bibliography", "references", "notes", "acknowledg", "glossary", "about the author")

PROMPT = prompt_files.chat_prompt("book_post")  # prompts/book_post.md

Outcome = Literal["posted", "skipped", "failed", "blocked", "gave_up", "tested"]


class BookPost(BaseModel):
    """A new Page post about one topic of the book, ending in a call to action."""

    post: str = Field(min_length=1, max_length=2000, description="The post: hook, one or two ideas from the topic, a "
                                                                 "call to action; [n] markers for passages used.")
    reason: str = Field(description="One sentence for the author: what angle the post takes and why.")
    headline: str = Field(default="", description="Headline for the post's picture: its hook or main question in "
                                                  "at most 8 words.")
    scene: str = Field(default="", description="One sentence: the picture's background, showing the post's idea (no "
                                               "text, logos or real people).")


PROMPT_VERSION = prompts.register("book_post", PROMPT, BookPost, {"humanize": HUMANIZE})


class Topic(BaseModel):
    """One chapter of a book's summary, as a topic for a post."""

    key: str  # "<source id>#<chapter index>"
    source_id: str
    title: str  # the chapter's title, or "Part n"
    summary: str


class PostState(TypedDict, total=False):
    topic: dict  # the Topic (as JSON, for the checkpointer)
    link: str  # where to get the book ("" = none)
    test: bool  # test mode: publish nothing
    humanize: int  # how human the post sounds (the schedule's humanize when the run started)
    chunk_ids: list[str]  # the passages the post is drawn from (kept for revisions)
    post: str
    reason: str
    revisions: int
    proposal_message_id: int
    decision: str  # approve | skip | feedback | edit
    own_text: bool  # the post is the author's own text (Edit), not a model's
    feedback: str
    outcome: Outcome
    posted_url: str
    with_picture: bool  # the post comes with a picture (the schedule's book_post_picture; "Without picture" ends it)
    headline: str  # the picture's headline and scene, from the post (BookPost)
    scene: str
    picture_path: str  # the current picture in Storage ("" = none)
    picture_sent: str  # the picture last sent to Telegram (not sent again with a rewritten text)
    picture_note: str  # why there is no picture ("" = none)
    pictures: int  # pictures made in this run


# ---------- choosing the topic ----------
def topics(source_ids: list[str]) -> list[Topic]:
    """All topics of the books, the books taking turns (chapter 1 of each, then chapter 2 of each, ...). Books
    without a summary have none; appendices and similar back matter (NOT_TOPICS) are left out."""
    per_book = []
    for sid in source_ids:
        summary = db.summaries.get(sid)
        if summary:
            per_book.append([Topic(key=f"{sid}#{i}", source_id=sid, title=c.chapter or f"Part {i + 1}",
                                   summary=c.summary) for i, c in enumerate(summary.chapters)
                             if not (c.chapter or "").strip().lower().startswith(NOT_TOPICS)])
    longest = max((len(t) for t in per_book), default=0)
    return [book[i] for i in range(longest) for book in per_book if i < len(book)]


def rotate(found: list[Topic], used: dict[str, datetime]) -> Topic | None:
    """The next topic: the first never used, else the one used longest ago."""
    fresh = [t for t in found if t.key not in used]
    if fresh:
        return fresh[0]
    return min(found, key=lambda t: used[t.key], default=None)


def used_topics(user_id: str) -> dict[str, datetime]:
    """Topic key → when it was last proposed (any outcome), from the cycle log and this process."""
    with _lock:
        used = dict(_used)
    try:
        for cycle in records.list_cycles(user_id, LOG_CYCLES):
            for e in cycle.entries:
                if e.kind == "post" and (e.item_id not in used or used[e.item_id] < e.proposed_at):
                    used[e.item_id] = e.proposed_at
    except OSError as e:  # DatabaseError: only this process's memory counts
        logger.warning("Book post: the cycle log cannot be read: %s", e)
    return used


def next_topic(settings: AutomationSettings) -> Topic | None:
    """The topic for this cycle's post, or None when no inbox book has a summary.

    Raises:
        InboxConfigError: If the books are not configured.
    """
    _, source_ids = inbox.inbox_books()
    return rotate(topics(source_ids), used_topics(settings.user_id))


# ---------- runs ----------
def is_book_post(thread_id: str) -> bool:
    return thread_id.startswith(PREFIX)


def start(topic: Topic, settings: AutomationSettings) -> str | None:
    """Write the post about the topic, send the proposal to Telegram and wait.

    Returns:
        The run's thread id, or None if it ended without waiting.

    Raises:
        GenerationError, TelegramError, FacebookError, DatabaseError: If drafting or sending fails.
    """
    thread_id = f"{PREFIX}{topic.key}:{db.new_id('run')}"
    with _lock:
        _used[topic.key] = db.now()
    with tracing.scope():
        _graph().invoke({"topic": topic.model_dump(mode="json"), "link": settings.book_links.get(topic.source_id, ""),
                         "test": settings.test_mode, "humanize": settings.humanize, "revisions": 0,
                         "with_picture": settings.book_post_picture and images.is_configured(), "pictures": 0},
                        _config(thread_id))
    if _waiting(thread_id):
        with _lock:
            _runs[topic.key] = thread_id
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
        _runs.pop(values["topic"]["key"], None)
        return values.get("outcome", "gave_up")


def restore() -> int:
    """On server start: the book post runs kept in the database (see page_inbox.restore). A waiting run becomes the
    current proposal again; every run's topic counts as proposed (for the rotation).

    Returns:
        How many waiting runs were restored.
    """
    restored = 0
    with _lock:
        for thread_id in checkpoints.thread_ids(PREFIX):
            state = _graph().get_state(_config(thread_id))
            key = thread_id[len(PREFIX):].rsplit(":", 1)[0]
            if "wait" in state.next:
                _runs[key] = thread_id
                restored += 1
            elif state.next or checkpoints.is_old(state.created_at):  # broken off by an error, or old
                checkpoints.delete(thread_id)
                continue
            if state.created_at:
                when = datetime.fromisoformat(state.created_at)
                if key not in _used or _used[key] < when:
                    _used[key] = when
    return restored


def waiting_run() -> tuple[str, int] | None:
    """The book post run that waits for the author, with its proposal's message id, or None."""
    with _lock:
        for thread_id in list(_runs.values()):
            if _waiting(thread_id):
                return thread_id, _graph().get_state(_config(thread_id)).values["proposal_message_id"]
    return None


def posted_url(thread_id: str) -> str:
    """Where a finished run published its post ("" if it did not)."""
    return _graph().get_state(_config(thread_id)).values.get("posted_url", "") or ""


# ---------- Graph ----------
_lock = threading.RLock()
_runs: dict[str, str] = {}  # topic key → its run's thread id, while the run waits
_used: dict[str, datetime] = {}  # topic key → when it was proposed (in this process)


@cache
def _graph():
    builder = StateGraph(PostState)
    builder.add_node("draft", _draft)
    builder.add_node("propose", _propose)
    builder.add_node("wait", _wait)
    builder.add_node("revise", _draft)  # the same writer, now with the feedback and the current post
    builder.add_node("use_text", _use_text)
    builder.add_node("picture", _picture)
    builder.add_node("new_picture", _new_picture)
    builder.add_node("no_picture", _no_picture)
    builder.add_node("publish", _publish)
    builder.add_node("skip", _skip)
    builder.add_edge(START, "draft")
    builder.add_edge("draft", "picture")
    builder.add_edge("picture", "propose")
    builder.add_edge("propose", "wait")
    builder.add_conditional_edges("wait", _after_wait, ["publish", "skip", "revise", "use_text", "new_picture",
                                                        "no_picture", END])
    builder.add_edge("revise", "picture")
    builder.add_edge("use_text", "propose")
    builder.add_edge("new_picture", "picture")
    builder.add_edge("no_picture", "propose")
    builder.add_edge("publish", END)
    builder.add_edge("skip", END)
    return builder.compile(checkpointer=checkpoints.checkpointer())


def _draft(state: PostState) -> PostState:
    """Write the post (first draft, or a rewrite following the author's feedback)."""
    topic = Topic.model_validate(state["topic"])
    feedback = state.get("feedback", "")
    update: PostState = {}
    if state.get("chunk_ids"):  # a rewrite: the same passages
        passages = [(db.chunks[c], 0.0) for c in state["chunk_ids"] if c in db.chunks]
    else:
        project_id = db.sources[topic.source_id].project_id
        passages = retrieve_chunks(project_id, f"{topic.title}\n{topic.summary}", PASSAGES, [topic.source_id],
                                   operation="book_post")
        update = {"chunk_ids": [chunk.id for chunk, _ in passages]}
    with usage.tagged(source_id=topic.source_id):
        result, _ = structured(PROMPT, {
            "style": style_guidance(humanize := state.get("humanize", HUMANIZE)),
            "book": source_name(topic.source_id) or topic.source_id,
            "topic": topic.title, "summary": topic.summary, "link": state.get("link") or "(none)",
            "context": format_context(passages) or "(no passages)", "recent": _recent_posts(),
            "current": facebook.publishable_text(state.get("post", "")) or "(none yet)",
            "feedback": feedback or "(none)",
        }, BookPost, "book post", temperature_for(humanize))
    update.update({"post": result.post, "reason": result.reason, "feedback": "", "own_text": False,
                   "headline": result.headline.strip()[:images.MAX_HEADLINE_CHARS],
                   "scene": result.scene.strip()[:images.MAX_SCENE_CHARS]})
    if feedback:
        update["revisions"] = state.get("revisions", 0) + 1
    return update


def _recent_posts() -> str:
    """The latest own Page posts as <post> blocks ("(none)" when there are none or the Page cannot be read)."""
    try:
        posts = [p for p in facebook.list_posts(limit=RECENT_POSTS * 2).items if p.from_page and p.message.strip()]
    except facebook.FacebookError as e:
        logger.warning("Book post: the Page's posts cannot be read: %s", e)
        return "(none)"
    blocks = [quote_untrusted(p.message[:RECENT_TEXT], "post", date=f"{p.created_time:%d %b %Y}")
              for p in posts[:RECENT_POSTS]]
    return "\n\n".join(blocks) or "(none)"


def _propose(state: PostState) -> PostState:
    """Send the proposal to Telegram; the buttons of an earlier proposal go."""
    topic = Topic.model_validate(state["topic"])
    post = facebook.publishable_text(state["post"])
    blocked = bool(post) and output_blocked(post)
    test = state.get("test", False)
    if old := state.get("proposal_message_id"):
        inbox._quietly(telegram.remove_buttons, old)
    buttons = inbox.proposal_buttons(bool(post) and not blocked, test) + _picture_buttons(state)
    update: PostState = {}
    picture_line = _send_picture(state, update)
    lines = [inbox.PLATFORM_TAG["facebook"], "📣 A new post about your book" + (inbox.TEST_HEAD if test else ""),
             f"📖 {source_name(topic.source_id) or topic.source_id} · {topic.title}",
             f"Why: {facebook.publishable_text(state.get('reason', ''))}"]
    if picture_line:
        lines.append(picture_line)
    lines += inbox.revision_note(state)
    if blocked:
        lines += ["", "⚠️ The post looks like it contains instructions to an AI and will not be published. Answer "
                      "with feedback to rewrite it, ✏️ Edit to write it yourself, or skip."]
    else:
        lines += ["", "Your post:" if state.get("own_text") else "Proposed post:", post]
        if state.get("link"):
            lines.append(f"🔗 {state['link']}")
        lines += ["", "Answer “make it so” to publish it on your Page, “skip”, write what to change, or ✏️ Edit to "
                      "write it yourself."]
    update["proposal_message_id"] = telegram.send_message("\n".join(lines), buttons=buttons)
    return update


def _wait(state: PostState) -> PostState:
    """Stop until the author answers (runs twice: nothing else here)."""
    answer = interrupt({"proposal_message_id": state["proposal_message_id"]})
    return {"decision": answer["decision"], "feedback": answer.get("feedback", "")}


def _after_wait(state: PostState) -> str:
    decision = state["decision"]
    if decision == "approve":
        return "publish"
    if decision in ("skip", "answered"):
        return "skip"
    if decision == "edit":  # the author's own text: no limit, it costs no model call
        return "use_text"
    if decision == "new_picture" and state.get("with_picture") and state.get("pictures", 0) < MAX_PICTURES:
        return "new_picture"
    if decision in ("new_picture", "no_picture"):  # "no_picture", or no more pictures: on without one
        return "no_picture"
    if state.get("revisions", 0) >= MAX_REVISIONS:
        _drop_picture(state)
        inbox._quietly(telegram.remove_buttons, state["proposal_message_id"])
        inbox._quietly(telegram.send_message, f"That was {MAX_REVISIONS} rounds of changes; I leave this topic for "
                                              "now. Write the post yourself in the app if you like.")
        return END
    return "revise"


def _use_text(state: PostState) -> PostState:
    """The author's own text (after "Edit") becomes the post as it is."""
    return {"post": state["feedback"].strip(), "own_text": True, "feedback": ""}


def current_text(thread_id: str) -> str:
    """The post a run proposes now, as it would be posted."""
    return facebook.publishable_text(_graph().get_state(_config(thread_id)).values.get("post", ""))


def _publish(state: PostState) -> PostState:
    """Publish the post on the Page (in test mode: only say what would have been published)."""
    inbox._quietly(telegram.remove_buttons, state["proposal_message_id"])
    text = facebook.publishable_text(state["post"])
    if not text or output_blocked(text):
        inbox._quietly(telegram.send_message, "Not published: the post is empty or looks like it contains "
                                              "instructions to an AI.")
        return {"outcome": "blocked"}
    if state.get("test"):
        inbox._quietly(telegram.send_message, inbox.TEST_NOT_POSTED)
        _drop_picture(state)
        return {"outcome": "tested"}
    link = state.get("link") or ""
    try:
        picture = _current_picture(state)
        if picture:  # a photo post has no link preview: the link goes at the end of the text
            posted = facebook.publish_photo(text + (f"\n\n{link}" if link and link not in text else ""), picture)
        else:
            posted = facebook.publish_post(text, link=link or None)
    except (facebook.FacebookError, ValueError, OSError) as e:
        logger.warning("Book post: publishing failed: %s", e)
        inbox._quietly(telegram.send_message, f"Not published, Facebook said: {e}")
        return {"outcome": "failed"}
    _drop_picture(state)
    inbox._quietly(telegram.send_message, f"Published on your Page{' with the picture' if picture else ''}: "
                                          f"{posted.url}")
    return {"outcome": "posted", "posted_url": posted.url or ""}


# ---------- the picture ----------
def _picture(state: PostState) -> PostState:
    """Make the post's picture when the run has one and none is there yet (a rewritten text keeps its picture). A
    failure only leaves a note: the post goes on without a picture."""
    if not state.get("with_picture") or state.get("picture_path"):
        return {}
    topic = Topic.model_validate(state["topic"])
    source = db.sources.get(topic.source_id)
    count = state.get("pictures", 0) + 1
    headline = state.get("headline") or topic.title[:images.MAX_HEADLINE_CHARS]
    scene = state.get("scene", "")
    if output_blocked(f"{headline}\n{scene}"):  # model output from the book's passages: checked like the post
        headline, scene = topic.title[:images.MAX_HEADLINE_CHARS], ""
    try:
        if source is None:
            raise ValueError("the book is no longer in the library")
        with usage.tagged(source_id=source.id):
            made = images.generate_ad_image(
                book=source_name(source.id) or source.filename, about=ad_images.about_book(source.id),
                headline=headline, scene=scene, fmt=PICTURE_FORMAT, cover=ingestion.cover(source),
                project_id=source.project_id, source_id=source.id)
        png = ingestion.to_png(made.data, max_height=ad_images.MAX_PICTURE_HEIGHT)
        path = f"{source.project_id}/agent/{db.new_id('img')}.png"
        files.put(path, png, "image/png")
    except (GenerationError, ValueError, TimeoutError, OSError) as e:
        logger.warning("Book post: the picture could not be made: %s", e)
        return {"pictures": count, "picture_note": f"🖼 No picture this time: {e}"}
    return {"pictures": count, "picture_path": path, "picture_note": ""}


def _new_picture(state: PostState) -> PostState:
    """"New picture": the current one goes; the picture node makes another."""
    _drop_picture(state)
    return {"picture_path": ""}


def _no_picture(state: PostState) -> PostState:
    """"Without picture" (or no pictures left): the post goes on as a text post."""
    _drop_picture(state)
    return {"with_picture": False, "picture_path": "", "picture_note": ""}


def _picture_buttons(state: PostState) -> list[TelegramButton]:
    """The second row under a proposal with a picture: "New picture" (while pictures are left) and "Without
    picture"; after a failed picture: "Try a picture again"."""
    if not state.get("with_picture"):
        return []
    more = state.get("pictures", 0) < MAX_PICTURES
    if not state.get("picture_path"):
        return [TelegramButton(label="🖼 Try a picture again", data=inbox.BUTTON_NEW_PICTURE, row=1)] if more else []
    buttons = [TelegramButton(label="🔄 New picture", data=inbox.BUTTON_NEW_PICTURE, row=1)] if more else []
    return buttons + [TelegramButton(label="🚫 Without picture", data=inbox.BUTTON_NO_PICTURE, row=1)]


def _send_picture(state: PostState, update: PostState) -> str:
    """Send a new picture to Telegram (above the proposal; one already sent is not sent again) and return the line
    the proposal shows about it ("" when the post has none)."""
    if not state.get("with_picture"):
        return ""
    path = state.get("picture_path", "")
    if not path:
        return state.get("picture_note", "")
    if path != state.get("picture_sent"):
        try:
            picture = files.get(path)
            if picture is None:
                raise ValueError("the stored picture is missing")
            telegram.send_photo(picture, f"🖼 The picture for the post below: {state.get('headline', '')}")
        except (OSError, ValueError, telegram.TelegramError) as e:
            logger.warning("Book post: the picture could not be sent: %s", e)
            return "🖼 The picture could not be shown here; it is still posted with the text."
        update["picture_sent"] = path
    return f"🖼 With the picture above ({state.get('pictures', 1)} of at most {MAX_PICTURES})."


def _current_picture(state: PostState) -> bytes | None:
    """The PNG to post with the text, or None for a text post.

    Raises:
        ValueError: If the run has a picture but it is missing in Storage (nothing is posted then).
        FileStoreError: If Storage cannot be reached.
    """
    if not (state.get("with_picture") and state.get("picture_path")):
        return None
    picture = files.get(state["picture_path"])
    if picture is None:
        raise ValueError("the picture is missing; answer “without picture” to post the text alone")
    return picture


def _drop_picture(state: PostState) -> None:
    """Delete the run's current picture from Storage (it is on the Page, or not wanted)."""
    if path := state.get("picture_path"):
        ad_images.delete_files([path])


def _skip(state: PostState) -> PostState:
    inbox._quietly(telegram.remove_buttons, state["proposal_message_id"])
    _drop_picture(state)
    inbox._quietly(telegram.send_message, "Skipped. Nothing was published; the next cycle takes the next topic.")
    return {"outcome": "skipped"}


def _config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}, "run_name": "book_post", "tags": ["book_post", "agent"],
            "metadata": {"operation": "book_post", "prompt_version": PROMPT_VERSION}}


def _waiting(thread_id: str) -> bool:
    return bool(_graph().get_state(_config(thread_id)).next)
