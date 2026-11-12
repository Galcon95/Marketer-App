"""Page inbox agent (human in the loop): answer what readers write on the author's Facebook Page, with the author's
approval in Telegram. One run per item (a visitor's comment or visitor post, facebook.open_items):

    START ─► choose_book ─► analyze ─► propose ─► wait ⏸ ─(make it so)─► publish ─► END
                                          ▲         │
                                          │         ├─(skip)───────────► skip ────► END
                                          └─ revise ◄┘(feedback)

    choose_book  which of the configured books (FACEBOOK_INBOX_BOOKS) fits the item best: one vector search per book
                 for the reader's text, the best top similarity wins (no model call; one book: that one)
    analyze      the Discussion Relevance Agent in "own Page" mode (agents/discussion.py) drafts the reply; the result
                 is saved as a discussion analysis, so it also shows in the app. An analysis already made for this
                 item and not posted yet is reused (no second model run after a restart)
    propose      sends the item, the agent's recommendation and the proposed reply to the author's Telegram chat, with
                 the buttons "Make it so" and "Skip" (only "Skip" when there is nothing to post, or when the output
                 guard refuses the reply)
    wait         interrupt(): the run stops here and is stored by the checkpointer until the author answers. The
                 answer resumes it (resume()): approve, skip, or feedback with the author's words
    revise       one model call rewrites the reply to follow the feedback, from the same passages
                 (prompts/page_inbox_revise.md); saved in the analysis as the author's edit; then propose again
    publish      the output guard once more, then the reply goes up as the Page: under the comment's thread
                 (facebook.reply_to_comment) or under the visitor post (facebook.comment_on_post); the analysis gets
                 replied_id/url/at; Telegram gets the link
    skip         nothing is posted; the item is not proposed again (until a restart: see below)

Human in the loop: nothing is posted without the author's "make it so" (the button, or that text in the chat). A
decision is applied once: resume() only accepts an answer to the run's current proposal while the run waits, under a
lock; a second press, an answer to an older proposal or to a finished run is refused (the caller tells the author). The
revise loop ends after MAX_REVISIONS rounds: the author finishes that reply in the app.

Paused runs are kept in memory (MemorySaver): after a server restart a waiting proposal is gone and the item, still
unanswered on Facebook, is proposed anew; skipped items too (the set of decided items is in memory as well).

The reader's text is untrusted: it reaches the models only as quoted data (the Discussion agent's own guard, and a
<post> block under guard.UNTRUSTED_RULE in revise), and Telegram gets it as plain text. The feedback is the author's
own instruction: Telegram updates from anyone else never get here (social/telegram.py). Runs are traced in LangSmith
as "page_inbox" when tracing is on.
"""

import logging
import re
import threading
from functools import cache
from typing import Literal, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from pydantic import BaseModel, Field

from app.agents import discussion
from app.core import config, prompt_files, prompts, tracing
from app.core import state as db
from app.core.guard import clean_text, output_blocked, quote_untrusted
from app.core.llm import structured
from app.core.schemas import DiscussionAnalysis, DiscussionRequest, FacebookInboxItem, TelegramButton
from app.core.style import style_guidance, temperature_for
from app.db import records
from app.rag.retrieval import format_context, retrieve_chunks, source_name
from app.social import facebook, telegram

logger = logging.getLogger(__name__)

HUMANIZE = 80  # "how human" the replies sound (as the Discussions default)
MAX_DISCUSSION = 8000  # characters: the Discussion agent's limit (DiscussionRequest.discussion)
EXCERPT = 600  # characters of the post and of the reader's text shown in Telegram
MAX_REVISIONS = 5  # feedback rounds per item; then the author finishes the reply in the app
BOOK_SEARCH_K = 3  # passages per book when choosing the book

APPROVE = "make it so"
BUTTON_GO, BUTTON_SKIP = "go", "skip"

REVISE_PROMPT = prompt_files.chat_prompt("page_inbox_revise")  # prompts/page_inbox_revise.md


class Revision(BaseModel):
    """The reply rewritten to follow the author's feedback."""

    reply: str = Field(min_length=1, description="The new reply, plain text with [n] markers for the passages used.")


PROMPT_VERSION = prompts.register("page_inbox", REVISE_PROMPT, Revision, {"humanize": HUMANIZE})

Decision = Literal["approve", "skip", "feedback"]
Outcome = Literal["posted", "skipped", "failed", "blocked", "gave_up"]  # gave_up: too many revisions


class InboxState(TypedDict, total=False):
    """State of one run: one item on the Page, from finding it to the author's decision."""

    item: dict  # the FacebookInboxItem (as JSON, so the checkpointer can store it)
    source_ids: list[str]  # the books it may be answered from
    source_id: str  # the book chosen
    analysis_id: str  # the saved discussion analysis with the proposed reply
    revisions: int  # feedback rounds so far
    proposal_message_id: int  # the Telegram message the author answers (the one with the buttons)
    decision: Decision
    feedback: str
    outcome: Outcome
    posted_url: str


class InboxConfigError(RuntimeError):
    """FACEBOOK_INBOX_BOOKS is missing or names a book that is not processed."""


# ---------- Public API ----------
def inbox_books() -> tuple[str, list[str]]:
    """The project and the books the inbox answers from (FACEBOOK_INBOX_BOOKS, one client's processed books).

    Raises:
        InboxConfigError: If none is configured, one is unknown or not processed, or they belong to different clients.
    """
    ids = config.FACEBOOK_INBOX_BOOKS
    if not ids:
        raise InboxConfigError("Set FACEBOOK_INBOX_BOOKS in server/.env: the book ids (src_...) to answer from.")
    sources = [db.sources.get(i) for i in ids]
    if any(s is None or s.status != "ready" for s in sources):
        raise InboxConfigError("FACEBOOK_INBOX_BOOKS names a book that does not exist or is not processed.")
    projects = {s.project_id for s in sources}
    if len(projects) != 1:
        raise InboxConfigError("The books in FACEBOOK_INBOX_BOOKS must belong to one client.")
    return projects.pop(), ids


def start(item: FacebookInboxItem) -> str | None:
    """Start a run for one item: choose the book, draft the reply, send the proposal to Telegram and wait.

    Returns:
        The run's thread id (the run now waits for the author), or None when it ended without waiting (it should not;
        kept for safety).

    Raises:
        InboxConfigError: If the books are not configured.
        GenerationError, BookNotReady, TelegramError, DatabaseError: If drafting, sending or saving fails; the item is
            not marked decided, so it is proposed again later.
    """
    _, source_ids = inbox_books()
    thread_id = f"{item.id}:{db.new_id('run')}"
    with tracing.scope():
        _graph().invoke({"item": item.model_dump(mode="json"), "source_ids": source_ids, "revisions": 0},
                        _config(thread_id))
    if _waiting(thread_id):
        with _lock:
            _runs[item.id] = thread_id
        return thread_id
    return None


def resume(thread_id: str, message_id: int, decision: Decision, feedback: str = "") -> Outcome | Literal[
        "waiting", "stale"]:
    """Apply the author's answer to a waiting run, exactly once.

    Args:
        thread_id: The run.
        message_id: The Telegram message the answer refers to; only the run's current proposal counts.
        decision: approve ("make it so"), skip, or feedback.
        feedback: The author's words, for feedback.

    Returns:
        "stale" if the run does not wait or the answer is not to its current proposal (nothing done); "waiting" after
        feedback (a new proposal was sent); else the outcome (posted, skipped, failed, blocked, gave_up).
    """
    with _lock:  # one answer at a time: a second press waits, then finds the run decided
        state = _graph().get_state(_config(thread_id))
        if not _waiting(thread_id) or state.values.get("proposal_message_id") != message_id:
            return "stale"
        with tracing.scope():
            _graph().invoke(Command(resume={"decision": decision, "feedback": feedback}), _config(thread_id))
        if _waiting(thread_id):
            return "waiting"
        values = _graph().get_state(_config(thread_id)).values
        item_id = values["item"]["id"]
        if values.get("outcome") in ("posted", "skipped", "blocked") or not values.get("outcome"):
            _decided.add(item_id)
        _runs.pop(item_id, None)
        return values.get("outcome", "gave_up")


def waiting_run() -> tuple[str, int] | None:
    """The run that waits for the author, with its current proposal's message id (at most one at a time), or None."""
    with _lock:
        for thread_id in list(_runs.values()):
            if _waiting(thread_id):
                return thread_id, _graph().get_state(_config(thread_id)).values["proposal_message_id"]
    return None


def is_open(item: FacebookInboxItem) -> bool:
    """True if the item has neither been decided nor has a run yet."""
    with _lock:
        return item.id not in _decided and item.id not in _runs


def parse_answer(text: str) -> tuple[Decision, str]:
    """The author's text in Telegram as a decision: "make it so" approves, "skip" skips (case, spaces and closing
    punctuation do not matter), anything else is feedback for the reply."""
    plain = re.sub(r"[\s.!]+$", "", " ".join(text.split()).lower())
    if plain == APPROVE:
        return "approve", ""
    if plain == "skip":
        return "skip", ""
    return "feedback", text.strip()


def button_decision(data: str) -> Decision | None:
    """A button's data as a decision, None for an unknown button."""
    return {BUTTON_GO: "approve", BUTTON_SKIP: "skip"}.get(data)


# ---------- Graph ----------
_checkpointer = MemorySaver()
_lock = threading.RLock()
_runs: dict[str, str] = {}  # item id → its run's thread id, while the run waits
_decided: set[str] = set()  # items posted, skipped or handed to the app: not proposed again


@cache
def _graph():
    """Build and compile the graph with the in-memory checkpointer (needed for interrupt)."""
    builder = StateGraph(InboxState)
    builder.add_node("choose_book", _choose_book)
    builder.add_node("analyze", _analyze)
    builder.add_node("propose", _propose)
    builder.add_node("wait", _wait)
    builder.add_node("revise", _revise)
    builder.add_node("publish", _publish)
    builder.add_node("skip", _skip)
    builder.add_edge(START, "choose_book")
    builder.add_edge("choose_book", "analyze")
    builder.add_edge("analyze", "propose")
    builder.add_edge("propose", "wait")
    builder.add_conditional_edges("wait", _after_wait, ["publish", "skip", "revise", END])
    builder.add_edge("revise", "propose")
    builder.add_edge("publish", END)
    builder.add_edge("skip", END)
    return builder.compile(checkpointer=_checkpointer)


def _choose_book(state: InboxState) -> InboxState:
    """The book whose best passage is most similar to the reader's text (one book: that one)."""
    ids = state["source_ids"]
    if len(ids) == 1:
        return {"source_id": ids[0]}
    project_id = db.sources[ids[0]].project_id
    text = clean_text(state["item"]["message"])[:2000]
    best = max(ids, key=lambda sid: max(
        (score for _, score in retrieve_chunks(project_id, text, BOOK_SEARCH_K, [sid], operation="page_inbox")),
        default=0.0))
    return {"source_id": best}


def _analyze(state: InboxState) -> InboxState:
    """Draft the reply with the Discussion agent (own Page mode) and save it; reuse an earlier, unposted analysis."""
    item = FacebookInboxItem.model_validate(state["item"])
    project_id = db.sources[state["source_id"]].project_id
    earlier = next((a for a in records.list_discussions(project_id)
                    if a.facebook_comment_id == item.id and not a.replied_id), None)
    if earlier:
        return {"analysis_id": earlier.id}
    request = DiscussionRequest(
        source_id=state["source_id"], discussion=_as_discussion(item), url=item.permalink_url or "",
        platform="facebook", humanize=HUMANIZE, facebook_comment_id=item.id)
    analysis = discussion.analyze_discussion(project_id, request)
    records.save_discussion(analysis)
    return {"analysis_id": analysis.id}


def _propose(state: InboxState) -> InboxState:
    """Send the proposal to Telegram (buttons under it); the buttons of an earlier proposal are removed."""
    item = FacebookInboxItem.model_validate(state["item"])
    analysis = _analysis(state)
    reply = facebook.publishable_text(analysis.reply)
    blocked = bool(reply) and output_blocked(reply)
    if old := state.get("proposal_message_id"):
        _quietly(telegram.remove_buttons, old)
    buttons = [TelegramButton(label="Skip", data=BUTTON_SKIP)]
    if reply and not blocked:
        buttons.insert(0, TelegramButton(label="✅ Make it so", data=BUTTON_GO))
    message_id = telegram.send_message(_proposal_text(item, analysis, reply, blocked, state), buttons=buttons)
    return {"proposal_message_id": message_id}


def _wait(state: InboxState) -> InboxState:
    """Stop until the author answers; the answer is what resume() passes (interrupt runs again on resume and returns
    it). Nothing else happens here, because this node is run twice."""
    answer = interrupt({"proposal_message_id": state["proposal_message_id"]})
    return {"decision": answer["decision"], "feedback": answer.get("feedback", "")}


def _after_wait(state: InboxState) -> str:
    """Route the author's decision; feedback beyond MAX_REVISIONS ends the run (finish it in the app)."""
    decision = state["decision"]
    if decision == "approve":
        return "publish"
    if decision == "skip":
        return "skip"
    if state.get("revisions", 0) >= MAX_REVISIONS:  # ends without an outcome: handed to the app
        _quietly(telegram.remove_buttons, state["proposal_message_id"])
        _quietly(telegram.send_message, f"That was {MAX_REVISIONS} rounds of changes. Please finish this reply in the "
                                        "app (Discussions), where it is saved.")
        return END
    return "revise"


def _revise(state: InboxState) -> InboxState:
    """Rewrite the reply to follow the author's feedback, from the same passages; saved as the author's edit."""
    analysis = _analysis(state)
    passages = [(db.chunks[c.chunk_id], c.score) for c in analysis.citations if c.chunk_id in db.chunks]
    revision, _ = structured(REVISE_PROMPT, {
        "style": style_guidance(HUMANIZE), "book": source_name(analysis.source_id) or analysis.source_id,
        "discussion": quote_untrusted(analysis.discussion, "post", platform="facebook"),
        "context": format_context(passages) or "(no passages)",
        "reply": facebook.publishable_text(analysis.reply) or "(none yet)", "feedback": state["feedback"],
    }, Revision, "revised reply", temperature_for(HUMANIZE))
    records.save_discussion(analysis.model_copy(update={"reply": revision.reply, "edited": True,
                                                        "updated_at": db.now()}))
    return {"revisions": state.get("revisions", 0) + 1, "feedback": ""}


def _publish(state: InboxState) -> InboxState:
    """Post the reply as the Page, once: an analysis already replied is not posted again."""
    item = FacebookInboxItem.model_validate(state["item"])
    analysis = _analysis(state)
    _quietly(telegram.remove_buttons, state["proposal_message_id"])
    if analysis.replied_id:
        _quietly(telegram.send_message, f"Already posted: {analysis.replied_url}")
        return {"outcome": "posted", "posted_url": analysis.replied_url}
    text = facebook.publishable_text(analysis.reply)
    if not text or output_blocked(text):
        _quietly(telegram.send_message, "Not posted: the reply is empty or looks like it contains instructions to an "
                                        "AI. Check it in the app (Discussions).")
        return {"outcome": "blocked"}
    try:
        if item.kind == "visitor_post":
            posted = facebook.comment_on_post(item.reply_to, text)
        else:
            posted = facebook.reply_to_comment(item.reply_to, text)
    except (facebook.FacebookError, ValueError) as e:
        logger.warning("Page inbox: posting the reply to %s failed: %s", item.id, e)
        _quietly(telegram.send_message, f"Not posted, Facebook said: {e}\nThe reply is saved in the app (Discussions).")
        return {"outcome": "failed"}
    try:
        records.save_discussion(analysis.model_copy(update={
            "replied_id": posted.id, "replied_url": posted.url, "replied_at": db.now(), "updated_at": db.now()}))
    except OSError:  # DatabaseError: it is on Facebook, only the app's record is missing
        logger.exception("Page inbox: reply %s posted but not saved", posted.id)
    _quietly(telegram.send_message, f"Posted on your Page: {posted.url}")
    return {"outcome": "posted", "posted_url": posted.url}


def _skip(state: InboxState) -> InboxState:
    """Nothing is posted; the proposal's buttons go."""
    _quietly(telegram.remove_buttons, state["proposal_message_id"])
    _quietly(telegram.send_message, "Skipped. Nothing was posted.")
    return {"outcome": "skipped"}


# ---------- helpers ----------
def _config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}, "run_name": "page_inbox", "tags": ["page_inbox", "agent"],
            "metadata": {"prompt_version": PROMPT_VERSION}}


def _waiting(thread_id: str) -> bool:
    """True if the run is paused at wait."""
    return "wait" in _graph().get_state(_config(thread_id)).next


def _analysis(state: InboxState) -> DiscussionAnalysis:
    analysis = records.get_discussion(state["analysis_id"])
    if analysis is None:
        raise LookupError(f"Discussion analysis {state['analysis_id']} is gone.")
    return analysis


def _as_discussion(item: FacebookInboxItem) -> str:
    """The item as a discussion for the agent (as commentAsDiscussion in the client), within the agent's limit."""
    if item.kind == "visitor_post":
        text = f"A post by {item.author or 'a reader'} on my Facebook Page:\n{item.message}"
    else:
        post = item.post.message or "(a photo or video without text)"
        text = f"My post on my Facebook Page:\n{post}\n\nComment by {item.author or 'a reader'}:\n{item.message}"
    return clean_text(text)[:MAX_DISCUSSION]


def _proposal_text(item: FacebookInboxItem, analysis: DiscussionAnalysis, reply: str, blocked: bool,
                   state: InboxState) -> str:
    """The Telegram message: what was written, the book, the agent's view and the reply, and how to answer."""
    who = item.author or "A reader"
    head = (f"💬 New comment by {who} on your Page" if item.kind == "comment"
            else f"📝 New post by {who} on your Page")
    lines = [head]
    if item.kind == "comment" and item.post.message:
        lines.append(f"Your post: {_excerpt(item.post.message)}")
    lines += [f"{who}: {_excerpt(item.message)}"]
    if item.permalink_url:
        lines.append(item.permalink_url)
    lines += ["", f"📖 {source_name(analysis.source_id) or analysis.source_id}",
              f"Agent: {analysis.recommendation} – {facebook.publishable_text(analysis.reason)}"]
    if state.get("revisions"):
        lines.append(f"(revised {state['revisions']}×)")
    if blocked:
        lines += ["", "⚠️ The reply looks like it contains instructions to an AI and will not be posted. Answer with "
                      "feedback to rewrite it, or skip."]
    elif reply:
        lines += ["", "Proposed reply:", reply, "",
                  "Answer “make it so” to post it, “skip”, or write what to change."]
    else:
        lines += ["", "No reply proposed. Write what the reply should say, or skip."]
    return "\n".join(lines)


def _excerpt(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= EXCERPT else text[:EXCERPT].rsplit(" ", 1)[0] + " …"


def _quietly(fn, *args) -> None:
    """A Telegram call whose failure must not stop the run (a notice or removing buttons); logged."""
    try:
        fn(*args)
    except telegram.TelegramError as e:
        logger.warning("Page inbox: Telegram %s failed: %s", fn.__name__, e)
