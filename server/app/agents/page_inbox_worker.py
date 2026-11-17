"""The Page inbox agent's worker: a background thread that connects Telegram, the Facebook Page, the YouTube channel
and the graph (agents/page_inbox.py) while the server runs.

    loop:  get_updates (long poll) ─► handle each update ─► every FACEBOOK_INBOX_INTERVAL min: propose_next()

    /next             look at the Page and the channel now and propose the next open item
    /start, /help     what the bot does and how to answer
    a button          "Make it so" / "Skip" under the current proposal
    a text            "make it so", "skip", or feedback for the current proposal (a Telegram "Reply" to an older
                      proposal is refused: only the current one counts)

One proposal at a time: nothing new is proposed while one waits for the author. A waiting proposal whose comment was
answered elsewhere in the meantime (in the app, or on Facebook) is taken back on the next look at the Page, so it does
not block the newer comments. After a decision the next open item is proposed right away, so the author can work
through the Page in one go. The schedule only proposes when something new is there; /next always answers (also
"Nothing new").

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
import time

from app.agents import page_inbox as inbox
from app.core import config
from app.core.llm import GenerationError
from app.core.schemas import TelegramUpdate
from app.social import facebook, telegram, youtube

logger = logging.getLogger(__name__)

POLL_WAIT = 25  # seconds a long poll waits for an update
ERROR_PAUSE = 10  # seconds to wait after a failed poll
SCAN_POSTS = 10  # latest posts looked at per scan
SCAN_COMMENTS = 50  # latest YouTube comment threads looked at per scan (1-3 quota units)

HELP = ("I watch your Facebook Page and your YouTube channel and propose replies to readers' comments, drafted from "
        "your books.\n\n"
        "Under a proposal: press ✅ Make it so (or write “make it so”) to post it as your Page or channel, Skip to "
        "leave it, or write what to change and I rewrite it.\n\n/next – look at the Page and the channel now")


class InboxWorker:
    """Polls Telegram and runs the inbox; `handle` and `tick` do one step each (tests call them directly)."""

    def __init__(self, interval_minutes: float):
        self.interval = interval_minutes * 60  # 0: no schedule, only /next
        self.offset: int | None = None
        self.last_scan = 0.0
        self.last_error = ""  # the last scan error reported in Telegram (the schedule reports each error once)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ----- lifecycle -----
    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="page-inbox", daemon=True)
        self._thread.start()
        logger.info("Page inbox worker started (scan every %s min, /next in Telegram)", self.interval / 60 or "—")

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)  # a long poll may still be open; the thread is a daemon

    def _run(self) -> None:
        self.last_scan = time.monotonic()  # the first scheduled scan after one interval; /next any time
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
            self.tick(time.monotonic())

    # ----- one step -----
    def tick(self, now: float) -> None:
        """The schedule: when the interval has passed, look at the Page: take back a waiting proposal that was
        answered elsewhere, and propose the next open item when nothing waits."""
        if not self.interval or now - self.last_scan < self.interval:
            return
        self.last_scan = now
        self.propose_next(asked=False)

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

    def propose_next(self, asked: bool) -> bool:
        """Look at the Page and the channel and start a run for the oldest open item. `asked`: the author sent /next
        (always answer).

        Returns:
            True if a proposal was sent.
        """
        try:
            items, failed = self._open_items(asked)
            if waiting := inbox.waiting_run():
                # still unanswered: it keeps waiting; answered elsewhere: take it back and go on (not when a source
                # could not be read: then its item may only seem answered)
                if failed or inbox.item_of(waiting[0]) in {i.id for i in items} or not inbox.withdraw(*waiting):
                    if asked:
                        self._say("A proposal is still waiting for your answer (above).", reply_to=waiting[1])
                    return False
            item = next((i for i in items if inbox.is_open(i)), None)
            if item is None:
                if asked and not failed:
                    self._say("Nothing new on your Page or channel.")
                return False
            if asked:
                self._say("Drafting a reply…")
            inbox.start(item)
            self.last_error = ""
            return True
        except (facebook.FacebookError, youtube.YouTubeError, telegram.TelegramError, GenerationError,
                inbox.InboxConfigError, LookupError, OSError) as e:
            self._report(f"Could not prepare the next reply: {e}", asked)
            return False

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
        if asked or message != self.last_error:
            self._say(message)
        self.last_error = message

    # ----- helpers -----
    def _button(self, update: TelegramUpdate) -> None:
        decision = inbox.button_decision(update.text)
        waiting = inbox.waiting_run()
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
            self.propose_next(asked=True)
            return
        waiting = inbox.waiting_run()
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
            result = inbox.resume(thread_id, message_id, decision, feedback)
        except (GenerationError, telegram.TelegramError, LookupError, OSError) as e:
            logger.warning("Page inbox: applying the decision failed: %s", e)
            self._say(f"That did not work: {e}\nThe proposal above still waits; try again.")
            return
        if result == "stale":
            self._say("This proposal is already decided.")
        elif result != "waiting":
            self.propose_next(asked=False)

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
    _worker = InboxWorker(config.FACEBOOK_INBOX_INTERVAL)
    _worker.start()
    return _worker


def stop() -> None:
    if _worker:
        _worker.stop()
