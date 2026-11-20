"""One cycle of the marketing agent and its log (private.automation_cycles).

A cycle starts on the schedule, from the app ("Run now") or from Telegram (/next) and goes through its phases:

    replies   answer what readers wrote on the Page and the channel, one proposal at a time   (page_inbox.py)
    comment   no new comments: a question under a recent post                                   (engagement.py)
    post      a book topic as a new post with a call to action                                  (book_post.py)

The worker (page_inbox_worker.py) drives it; this module only records it. Each proposal becomes a CycleEntry; the
author's decision fills in its outcome. A cycle is saved once it has something to show (a proposal, or an error):
the schedule's many quiet looks ("nothing new") are not logged; the Agent Workspace's "Last run" shows them.

Waiting proposals are kept in the database (agents/checkpoints.py), so on the next server start the cycle whose
proposal still waits goes on (continue_after_restart); any other cycle still "running" is marked "interrupted". Saving
never breaks the agent: a database error is logged.
"""

import logging
from collections import Counter

from app.core import state as db
from app.core.schemas import AutomationCycle, CycleEntry, CycleOutcome, CycleTrigger
from app.db import records

logger = logging.getLogger(__name__)

EXCERPT = 140  # characters of the reader's text kept in the log

# How each outcome reads in the summary message, in this order.
SUMMARY_WORDS: dict[CycleOutcome, str] = {
    "posted": "posted", "tested": "approved in test mode (not posted)", "skipped": "skipped",
    "answered": "answered elsewhere", "blocked": "blocked by the guard",
    "failed": "failed to post", "gave_up": "handed to the app", "waiting": "still waiting",
}


class Cycle:
    """A running cycle: what it proposed and what the author decided."""

    def __init__(self, user_id: str, trigger: CycleTrigger):
        self.record = AutomationCycle(id=db.new_id("cyc"), user_id=user_id, trigger=trigger, started_at=db.now())
        self.post_tried = False  # phase 3 ran in this cycle (once per cycle)
        self.engage_tried: set[str] = set()  # the platforms phase 2 ran for in this cycle (once each)

    @classmethod
    def of(cls, record: AutomationCycle) -> "Cycle":
        """A saved running cycle, to go on with (after a server restart)."""
        cycle = cls(record.user_id, record.trigger)
        cycle.record = record
        cycle.post_tried = any(e.kind == "post" for e in record.entries)
        cycle.engage_tried = {e.platform for e in record.entries if e.kind == "comment"}
        return cycle

    @property
    def asked(self) -> bool:
        """The author started it (app or Telegram), so it always answers, also "nothing new"."""
        return self.record.trigger != "schedule"

    def proposed(self, thread_id: str, item) -> None:
        """A proposal for an inbox item (FacebookInboxItem or YouTubeInboxItem) was sent to the author."""
        text = " ".join(item.message.split())
        self.record.entries.append(CycleEntry(
            kind="reply", platform=item.platform, item_id=item.id, thread_id=thread_id, author=item.author or "",
            excerpt=text[:EXCERPT] + ("…" if len(text) > EXCERPT else ""), proposed_at=db.now()))
        self._save()

    def proposed_comment(self, thread_id: str, post) -> None:
        """A question under the author's own post (a FacebookPost) or video (a YouTubeUpload) was proposed
        (phase 2)."""
        youtube = getattr(post, "platform", "facebook") == "youtube"
        text = " ".join((post.title if youtube else post.message).split())
        self.record.entries.append(CycleEntry(
            kind="comment", platform="youtube" if youtube else "facebook", item_id=post.id, thread_id=thread_id,
            author="",
            excerpt=text[:EXCERPT] + ("…" if len(text) > EXCERPT else ""), proposed_at=db.now()))
        self._save()

    def proposed_post(self, thread_id: str, topic, book: str) -> None:
        """A new post about a book topic (a book_post.Topic) was proposed (phase 3)."""
        self.record.entries.append(CycleEntry(
            kind="post", platform="facebook", item_id=topic.key, thread_id=thread_id, author="",
            excerpt=f"{book} · {topic.title}"[:EXCERPT], proposed_at=db.now()))
        self._save()

    def revised(self, thread_id: str) -> None:
        """The author gave feedback: the proposal was rewritten and sent again."""
        if entry := self._entry(thread_id):
            entry.revisions += 1
            self._save()

    def decided(self, thread_id: str, outcome: CycleOutcome, url: str = "") -> None:
        """The proposal's run ended with this outcome."""
        if entry := self._entry(thread_id):
            entry.outcome, entry.url, entry.decided_at = outcome, url, db.now()
            self._save()

    def finish(self, status: str = "done", note: str = "") -> None:
        """The cycle ended (done, or error with a note); saved when it has something to show."""
        self.record.status, self.record.note, self.record.ended_at = status, note, db.now()
        if self.record.entries or note:
            self._save()

    def summary(self) -> str:
        """E.g. "Cycle done: 2 posted, 1 skipped." ("" when nothing was proposed)."""
        counts = Counter(e.outcome for e in self.record.entries)
        parts = [f"{counts[o]} {word}" for o, word in SUMMARY_WORDS.items() if counts[o]]
        return f"Cycle done: {', '.join(parts)}." if parts else ""

    def _entry(self, thread_id: str) -> CycleEntry | None:
        return next((e for e in self.record.entries if e.thread_id == thread_id), None)

    def _save(self) -> None:
        try:
            records.save_cycle(self.record)
        except OSError as e:  # DatabaseError: the cycle goes on, only its log is missing
            logger.warning("Could not save the agent's cycle %s: %s", self.record.id, e)


def continue_after_restart(user_id: str, waiting_thread: str | None) -> Cycle | None:
    """On server start: the running cycle that holds the waiting proposal (`waiting_thread`, restored from the
    database) goes on and is returned; every other cycle still "running" is marked interrupted. None when no cycle
    holds it (or there is no waiting proposal)."""
    keep = None
    try:
        if waiting_thread and user_id:
            keep = next((c for c in records.list_cycles(user_id, 5) if c.status == "running"
                         and any(e.thread_id == waiting_thread for e in c.entries)), None)
        if count := records.interrupt_running_cycles(db.now(), keep.id if keep else None):
            logger.info("Marked %s unfinished agent cycle(s) as interrupted", count)
    except OSError as e:
        logger.warning("Could not check the unfinished agent cycles: %s", e)
    return Cycle.of(keep) if keep else None


def recent(user_id: str, limit: int = 20) -> list[AutomationCycle]:
    """The user's latest cycles, newest first.

    Raises:
        DatabaseError: If the database cannot be read.
    """
    return records.list_cycles(user_id, limit)
