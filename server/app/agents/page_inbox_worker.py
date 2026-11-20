"""The Page inbox agent's worker: a background thread that connects Telegram, the Facebook Page, the YouTube channel
and the graph (agents/page_inbox.py) while the server runs.

    loop:  get_updates (long poll) ─► handle each update ─► tick: when the schedule is due, run_cycle()

    /next             run a cycle now: look at the Page and the channel and propose the next open item
    /status           the schedule, the next and the last run, the running cycle
    /pause, /resume   stop the schedule for now, and start it again (the schedule itself is kept)
    /start, /help     what the bot does, all commands (COMMANDS, also the bot's "/" menu) and how to answer
    a button          "Make it so" / "Skip" under the current proposal
    a text            "make it so", "skip", or feedback for the current proposal (a Telegram "Reply" to an older
                      proposal is refused: only the current one counts)

One proposal at a time: nothing new is proposed while one waits for the author. A waiting proposal whose comment was
answered elsewhere in the meantime (in the app, or on Facebook) is taken back on the next look at the Page, so it does
not block the newer comments. After a decision the next open item is proposed right away, so the author can work
through the Page in one go. The schedule only proposes when something new is there; /next always answers (also
"Nothing new").

A cycle (agents/cycle.py) is one pass of the agent: started by the schedule, "Run now" in the app or /next, it
proposes the open items one at a time (each after the author's decision on the previous one) and ends when nothing is
left: then a summary goes to Telegram ("Cycle done: 2 posted, 1 skipped.") and the cycle is logged. Phases:

    1 replies   readers' new comments on the Page and the channel (page_inbox.py)
    2 comment   only when phase 1 found no reader's comment in this cycle: a question under an own recent post
                without comments, then one under an own recent video without comments (engagement.py; once per
                platform and cycle), if the schedule allows it (`engage`) and the daily limit is not reached
    3 post      once per cycle, after phases 1 and 2: a new post about the next topic of the books with a call to
                action (book_post.py), if the schedule allows it (`book_post`) and the daily limit is not reached

Test mode (the schedule's `test_mode`): every phase proposes as usual, but an approved proposal is not published.

While a proposal waits, a new start only checks it (answered elsewhere: taken back, and the cycle goes on). Only one
proposal waits at a time, of either agent; answers go to the agent whose proposal it is.

The schedule is the inbox owner's (agents/automation.py, set in the app under Phase 4 · Agent Workspace): manual, or
every N minutes, or at times of day. "Run now" in the app asks the worker for a run like /next (request_run); it
starts after the current long poll, within half a minute.

Items come from the Facebook Page (when FACEBOOK_PAGE_* is set) and from the YouTube channel the books' owner
connected in the app (page_inbox.channel_for_inbox), oldest first. When one of them cannot be read, the other is still
proposed, and a waiting proposal is kept (it cannot be checked).

Started by server.py on startup when Telegram and FACEBOOK_INBOX_BOOKS are configured (the Page and the channel are
looked at when they are there); one
worker per server process (Telegram allows only one long poll per bot: a second process gets "Conflict" and the
worker waits and retries). Errors never end the loop: they are logged and, where the author asked for something,
reported in Telegram.
"""

import logging
import threading
from datetime import UTC, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from app.agents import automation, book_post, engagement
from app.agents.cycle import Cycle, continue_after_restart
from app.agents import page_inbox as inbox
from app.core import config
from app.core.llm import GenerationError
from app.core.schemas import CycleTrigger, TelegramUpdate
from app.rag.retrieval import source_name
from app.social import facebook, telegram, youtube

logger = logging.getLogger(__name__)

POLL_WAIT = 25  # seconds a long poll waits for an update
ERROR_PAUSE = 10  # seconds to wait after a failed poll
SCAN_POSTS = 10  # latest posts looked at per scan
SCAN_COMMENTS = 50  # latest YouTube comment threads looked at per scan (1-3 quota units)

# The bot's commands: /help lists them, and they are Telegram's command menu (set on start, shown when typing "/").
COMMANDS: list[tuple[str, str]] = [
    ("next", "Run a cycle now: replies to new comments (with none, a question under a recent post of yours), "
             "then a new post about your book"),
    ("status", "The schedule, the next and the last run, the running cycle, and a waiting proposal"),
    ("pause", "Stop the schedule for now (/next still works; your schedule is kept)"),
    ("resume", "Start the schedule again (the next run counts from now)"),
    ("help", "All commands and how to answer a proposal"),
]

HELP = ("I am your marketing agent. I watch your Facebook Page and your YouTube channel and propose replies to "
        "readers' comments, drafted from your books. When nobody commented, I propose a question under one of your "
        "recent posts to start a discussion. At the end of a cycle I propose a new post about a topic of your book, "
        "with a call to action. Nothing is posted without your OK.\n\n"
        "Commands:\n" + "\n".join(f"/{name} – {text}" for name, text in COMMANDS) + "\n\n"
        "Under a proposal:\n"
        "✅ Make it so (button, or write “make it so”) – post it as your Page or channel\n"
        "Skip (button, or write “skip”) – post nothing, do not propose it again\n"
        "Any other text, e.g. “shorter, mention volume 2” – I rewrite the reply and ask again\n\n"
        "A proposal waits until you answer it; the next one follows your answer, and a cycle ends with a summary. "
        "The schedule is set in the app: Phase 4 · Agent Workspace.")

Step = Literal["proposed", "waiting", "none", "error"]


class InboxWorker:
    """Polls Telegram and runs the inbox; `handle` and `tick` do one step each (tests call them directly)."""

    def __init__(self):
        self.offset: int | None = None
        self.last_error = ""  # the last scan error reported in Telegram (the schedule reports each error once)
        self._error_told = False  # the last error was told to the author
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._run_requested = threading.Event()  # "Run now" in the app
        self.cycle: Cycle | None = None  # the running cycle

    # ----- lifecycle -----
    def start(self) -> None:
        try:
            telegram.set_commands(COMMANDS)
        except telegram.TelegramError as e:  # only the menu is missing; the commands work anyway
            logger.warning("Page inbox: could not set the bot's command menu: %s", e)
        self._thread = threading.Thread(target=self._run, name="page-inbox", daemon=True)
        self._thread.start()
        logger.info("Page inbox worker started (schedule from the app, /next in Telegram)")

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)  # a long poll may still be open; the thread is a daemon

    def request_run(self) -> None:
        """Ask for a run like /next (from the app); it starts after the current long poll."""
        self._run_requested.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                updates = telegram.get_updates(self.offset, wait=POLL_WAIT)
            except telegram.TelegramError as e:
                logger.warning("Page inbox: Telegram poll failed (%s): %s", e.status_code, e)
                self._stop.wait(e.retry_after or ERROR_PAUSE)
                continue
            self.offset = updates.next_offset
            for update in updates.items:
                self.handle(update)
            self.tick(datetime.now(UTC))

    # ----- one step -----
    def tick(self, now: datetime) -> None:
        """A run asked for in the app, or the schedule: when one is due, look at the Page: take back a waiting
        proposal that was answered elsewhere, and propose the next open item when nothing waits."""
        if self._run_requested.is_set():
            self._run_requested.clear()
            automation.inbox_ran(now)
            self._say("Run started from the app.")
            self.run_cycle("app")
            return
        if not automation.inbox_due(now):
            return
        automation.inbox_ran(now)
        self.run_cycle("schedule")

    def run_cycle(self, trigger: CycleTrigger) -> None:
        """Start a cycle, or (one still running, its proposal waiting) check on it and go on with it."""
        if self.cycle is None:
            self.cycle = Cycle(automation.inbox_owner() or "", trigger)
        self._step(asked=trigger != "schedule")

    def _step(self, asked: bool) -> None:
        """The cycle's next proposal; when there is none (or an error stopped it), the cycle ends."""
        result = self.propose_next(asked)
        if result in ("proposed", "waiting") or self.cycle is None:
            return
        if result == "none" and not any(e.kind == "reply" for e in self.cycle.record.entries):
            for platform in ("facebook", "youtube"):  # phase 2: no reader's comment in this cycle; once per platform
                if result != "none" or platform in self.cycle.engage_tried:
                    continue
                self.cycle.engage_tried.add(platform)
                result = self.propose_engagement(asked, platform)
                if result == "proposed":
                    return
        if result == "none" and not self.cycle.post_tried:  # phase 3: once per cycle
            self.cycle.post_tried = True
            result = self.propose_book_post(asked)
            if result == "proposed":
                return
        self._end_cycle(error=result == "error")

    def propose_engagement(self, asked: bool, platform: str = "facebook") -> Step:
        """Phase 2: a question under an own recent Facebook post or YouTube video without comments, when the
        schedule allows it."""
        owner = automation.inbox_owner()
        if not owner or (platform == "facebook" and not facebook.is_configured()):
            return "none"
        thing = "video" if platform == "youtube" else "post"
        try:
            settings = automation.schedule_of(owner)
            if not settings.engage:
                return "none"
            if engagement.posted_today(owner, settings.timezone) >= settings.daily_limit:
                if asked:
                    self._say(f"Daily limit reached ({settings.daily_limit} own comments or posts today), so no "
                              f"question under a {thing}.")
                return "none"
            post = engagement.pick_video(settings) if platform == "youtube" else engagement.pick_post(settings)
            if post is None:
                if asked:
                    self._say(f"No {thing} of yours from the last {settings.engage_days} days is waiting for a first "
                              "comment.")
                return "none"
            if asked:
                self._say(f"Drafting a question for your {thing}…")
            thread_id = engagement.start(post, test=settings.test_mode, humanize=settings.humanize)
            if thread_id and self.cycle:
                self.cycle.proposed_comment(thread_id, post)
            self.last_error = ""
            return "proposed" if thread_id else "none"
        except (facebook.FacebookError, youtube.YouTubeError, telegram.TelegramError, GenerationError,
                inbox.InboxConfigError, LookupError, OSError) as e:
            self._report(f"Could not prepare a question for your {thing}: {e}", asked)
            return "error"

    def propose_book_post(self, asked: bool) -> Step:
        """Phase 3: a new post about the next topic of the books, when the schedule allows it."""
        owner = automation.inbox_owner()
        if not owner or not facebook.is_configured():
            return "none"
        try:
            settings = automation.schedule_of(owner)
            if not settings.book_post:
                return "none"
            if engagement.posted_today(owner, settings.timezone) >= settings.daily_limit:
                if asked:
                    self._say(f"Daily limit reached ({settings.daily_limit} own comments or posts today), so no "
                              "new post about your book.")
                return "none"
            topic = book_post.next_topic(settings)
            if topic is None:
                if asked:
                    self._say("No topics for a book post yet: summarize your book in the app (Knowledge) first; its "
                              "chapters are the topics.")
                return "none"
            if asked:
                self._say("Writing a new post about your book…")
            thread_id = book_post.start(topic, settings)
            if thread_id and self.cycle:
                self.cycle.proposed_post(thread_id, topic, source_name(topic.source_id) or topic.source_id)
            self.last_error = ""
            return "proposed" if thread_id else "none"
        except (facebook.FacebookError, telegram.TelegramError, GenerationError, inbox.InboxConfigError,
                LookupError, OSError) as e:
            self._report(f"Could not prepare a post about your book: {e}", asked)
            return "error"

    def _end_cycle(self, error: bool) -> None:
        cycle, self.cycle = self.cycle, None
        if cycle is None:
            return
        if summary := cycle.summary():
            self._say(summary)
        # an error is logged when it was told to the author (asked, or new), not on every scheduled retry
        note = self.last_error if error and self._error_told else ""
        cycle.finish("error" if note else "done", note)

    def handle(self, update: TelegramUpdate) -> None:
        """One text or button press from the author."""
        try:
            if update.kind == "button":
                self._button(update)
            else:
                self._text(update)
        except Exception:  # never end the loop
            logger.exception("Page inbox: handling a Telegram update failed")
            self._say("Something went wrong on my side; it is logged. Try again, or use the app.")

    def propose_next(self, asked: bool) -> Step:
        """Look at the Page and the channel and start a run for the oldest open item. `asked`: the author started it
        (always answer). The running cycle records the proposal, and a proposal taken back.

        Returns:
            "proposed" (a proposal was sent), "waiting" (one still waits), "none" (nothing open), "error" (nothing
            could be read or prepared).
        """
        try:
            items, failed = self._open_items(asked)
            if (waiting := _waiting()) and _agent_of(waiting[0]) is not inbox:
                if asked:
                    self._say("A proposal is still waiting for your answer (above).", reply_to=waiting[1])
                return "waiting"
            if waiting:
                # still unanswered: it keeps waiting; answered elsewhere: take it back and go on (not when a source
                # could not be read: then its item may only seem answered)
                if failed or inbox.item_of(waiting[0]) in {i.id for i in items} or not inbox.withdraw(*waiting):
                    if asked:
                        self._say("A proposal is still waiting for your answer (above).", reply_to=waiting[1])
                    return "waiting"
                if self.cycle:
                    self.cycle.decided(waiting[0], "answered")
            item = next((i for i in items if inbox.is_open(i)), None)
            if item is None:
                proposed_before = bool(self.cycle and self.cycle.record.entries)
                if asked and not failed and not proposed_before:
                    self._say("Nothing new on your Page or channel.")
                return "error" if failed and not items else "none"
            if asked:
                self._say("Drafting a reply…")
            test, humanize = _style()
            thread_id = inbox.start(item, test=test, humanize=humanize)
            if thread_id and self.cycle:
                self.cycle.proposed(thread_id, item)
            self.last_error = ""
            return "proposed"
        except (facebook.FacebookError, youtube.YouTubeError, telegram.TelegramError, GenerationError,
                inbox.InboxConfigError, LookupError, OSError) as e:
            self._report(f"Could not prepare the next reply: {e}", asked)
            return "error"

    def _open_items(self, asked: bool) -> tuple[list, bool]:
        """The open items of the Page and the channel, oldest first, and whether one of them could not be read (its
        error is reported, like any scan error)."""
        items, failed = [], False
        if facebook.is_configured():
            try:
                items += facebook.open_items(posts=SCAN_POSTS)
            except facebook.FacebookError as e:
                self._report(f"Could not read your Facebook Page: {e}", asked)
                failed = True
        try:
            channel = inbox.channel_for_inbox()
            if channel:
                with youtube.as_channel(channel):
                    items += youtube.open_items(comments=SCAN_COMMENTS)
        except (youtube.YouTubeError, OSError) as e:
            self._report(f"Could not read your YouTube channel: {e}", asked)
            failed = True
        return sorted(items, key=lambda i: i.created_time), failed

    def _report(self, message: str, asked: bool) -> None:
        """Tell the author about an error: always when they asked (/next), else once until it changes."""
        logger.warning("Page inbox: %s", message)
        self._error_told = asked or message != self.last_error
        if self._error_told:
            self._say(message)
        self.last_error = message

    def _status(self) -> str:
        """The schedule, the next and the last run, and whether a proposal waits, in words."""
        owner = automation.inbox_owner()
        if not owner:
            return "No inbox books are set up (FACEBOOK_INBOX_BOOKS)."
        try:
            info = automation.status(owner)
        except OSError as e:  # DatabaseError
            return f"The schedule cannot be read right now: {e}"
        zone = info.schedule.timezone
        next_run = ("— paused (/resume)" if info.paused else _when(info.next_run, zone) if info.next_run
                    else "— (only /next)")
        lines = [f"Schedule: {automation.describe(info.schedule)}{' · PAUSED' if info.paused else ''}"
                 f"{' · TEST MODE (nothing is published)' if info.schedule.test_mode else ''}",
                 f"Next run: {next_run}",
                 f"Last run: {_when(info.last_run, zone) if info.last_run else '—'}"]
        if self.cycle:
            entries = self.cycle.record.entries
            done = sum(e.outcome != "waiting" for e in entries)
            lines.append(f"A cycle is running: {len(entries)} proposed, {done} decided.")
        if _waiting():
            lines.append("A proposal is waiting for your answer.")
        return "\n".join(lines) + "\n\nChange it in the app: Phase 4 · Agent Workspace."

    def _pause(self, paused: bool) -> str:
        """Pause or resume the schedule; the answer for the author."""
        owner = automation.inbox_owner()
        if not owner:
            return "No inbox books are set up (FACEBOOK_INBOX_BOOKS)."
        try:
            automation.set_paused(owner, paused)
            if paused:
                return "Paused: I no longer look on my own. /next still works; /resume starts the schedule again."
            info = automation.status(owner)
        except OSError as e:  # DatabaseError
            return f"That did not work, the schedule cannot be saved right now: {e}"
        when = _when(info.next_run, info.schedule.timezone) if info.next_run else "only when you ask (manual mode)"
        return f"Resumed. Next run: {when}."

    # ----- helpers -----
    def _button(self, update: TelegramUpdate) -> None:
        decision = inbox.button_decision(update.text)
        waiting = _waiting()
        if decision is None or waiting is None or waiting[1] != update.message_id:
            self._answer(update, "This proposal is already decided.")
            _remove(update.message_id)
            return
        self._answer(update, "Posting…" if decision == "approve" else "Skipping…")
        self._decide(waiting[0], update.message_id, decision, "")

    def _text(self, update: TelegramUpdate) -> None:
        command = update.text.strip().split()[0].split("@")[0].lower() if update.text.strip() else ""
        if command in ("/start", "/help"):
            self._say(HELP)
            return
        if command == "/next":
            self.run_cycle("telegram")
            return
        if command in ("/pause", "/resume"):
            self._say(self._pause(command == "/pause"))
            return
        if command == "/status":
            self._say(self._status())
            return
        waiting = _waiting()
        if waiting is None:
            self._say("Nothing is waiting for an answer. Send /next to look at your Page.")
            return
        thread_id, message_id = waiting
        if update.reply_to_message_id and update.reply_to_message_id != message_id:
            self._say("That proposal is no longer current; answer the latest one.", reply_to=message_id)
            return
        decision, feedback = inbox.parse_answer(update.text)
        if decision == "feedback":
            self._say("Rewriting…")
        self._decide(thread_id, message_id, decision, feedback)

    def _decide(self, thread_id: str, message_id: int, decision: str, feedback: str) -> None:
        """Resume the run; after a final decision, propose the next open item."""
        try:
            agent = _agent_of(thread_id)
            result = agent.resume(thread_id, message_id, decision, feedback)
        except (GenerationError, telegram.TelegramError, LookupError, OSError) as e:
            logger.warning("Page inbox: applying the decision failed: %s", e)
            self._say(f"That did not work: {e}\nThe proposal above still waits; try again.")
            return
        if result == "stale":
            self._say("This proposal is already decided.")
            return
        if result == "waiting":
            if self.cycle:
                self.cycle.revised(thread_id)
            return
        if self.cycle is None:  # e.g. a proposal from before the cycles: the decision starts one
            self.cycle = Cycle(automation.inbox_owner() or "", "telegram")
        self.cycle.decided(thread_id, result, agent.posted_url(thread_id) if result == "posted" else "")
        self._step(asked=False)

    def _say(self, text: str, reply_to: int | None = None) -> None:
        try:
            telegram.send_message(text, reply_to=reply_to)
        except telegram.TelegramError as e:
            logger.warning("Page inbox: could not send a Telegram message: %s", e)

    def _answer(self, update: TelegramUpdate, text: str) -> None:
        try:
            telegram.answer_button(update.callback_id or "", text)
        except telegram.TelegramError as e:
            logger.warning("Page inbox: could not confirm a button press: %s", e)


def _waiting() -> tuple[str, int] | None:
    """The proposal that waits for the author (thread id, message id), of any of the agents."""
    return inbox.waiting_run() or engagement.waiting_run() or book_post.waiting_run()


def _agent_of(thread_id: str):
    """The agent module a run belongs to (by its thread id's prefix)."""
    if engagement.is_engagement(thread_id):
        return engagement
    if book_post.is_book_post(thread_id):
        return book_post
    return inbox


def _style() -> tuple[bool, int]:
    """The schedule's test mode and how human the texts sound (off and the default when it cannot be read)."""
    owner = automation.inbox_owner()
    try:
        if owner:
            settings = automation.schedule_of(owner)
            return settings.test_mode, settings.humanize
    except OSError:
        pass
    return False, inbox.HUMANIZE


def _when(moment: datetime, timezone: str) -> str:
    """A time in the schedule's time zone, e.g. "Tue 18 Nov 09:00"."""
    return moment.astimezone(ZoneInfo(timezone)).strftime("%a %d %b %H:%M")


def _remove(message_id: int) -> None:
    try:
        telegram.remove_buttons(message_id)
    except telegram.TelegramError as e:
        logger.warning("Page inbox: could not remove buttons: %s", e)


# ---------- server start and stop ----------
_worker: InboxWorker | None = None


def start_if_configured() -> InboxWorker | None:
    """Start the worker when Telegram and the inbox books are configured (logs why not, otherwise). The Facebook
    Page (server/.env) and the YouTube channel (connected in the app) are each looked at when they are there."""
    global _worker
    missing = [name for name, ok in (("TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID", telegram.is_configured()),
                                     ("FACEBOOK_INBOX_BOOKS", bool(config.FACEBOOK_INBOX_BOOKS))) if not ok]
    if missing:
        logger.info("Page inbox worker off: %s not set", ", ".join(missing))
        return None
    try:
        inbox.inbox_books()
    except inbox.InboxConfigError as e:
        logger.warning("Page inbox worker off: %s", e)
        return None
    _worker = InboxWorker()
    _worker.cycle = _restore()
    _worker.start()
    return _worker


def _restore() -> Cycle | None:
    """The agents' runs kept in the database: a proposal that waited when the server stopped waits again (its buttons
    in Telegram still work), and its cycle goes on. Returns that cycle, or None."""
    try:
        restored = inbox.restore() + engagement.restore() + book_post.restore()
    except Exception:  # noqa: BLE001 (the database or a run cannot be read: start without them)
        logger.exception("Page inbox: the kept agent runs could not be restored")
        restored = 0
    waiting = _waiting() if restored else None
    if waiting:
        logger.info("Page inbox: a waiting proposal was restored (%s)", waiting[0])
    return continue_after_restart(automation.inbox_owner() or "", waiting[0] if waiting else None)


def is_running() -> bool:
    """True when the worker runs in this server process."""
    return _worker is not None


def request_run() -> bool:
    """Ask the worker for a run now (the app's "Run now"); False when it does not run."""
    if _worker is None:
        return False
    _worker.request_run()
    return True


def stop() -> None:
    global _worker
    if _worker:
        _worker.stop()
        _worker = None
