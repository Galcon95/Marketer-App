"""When the marketing agent runs on its own: every user's schedule (private.automation_settings) and the clock.

    schedule_of(user_id)         the user's settings (saved, or the defaults from FACEBOOK_INBOX_INTERVAL)
    save(user_id, schedule)      save the user's schedule; the next run counts from now
    set_paused(user_id, paused)  pause the schedule (/pause) or resume it (/resume); runs only when asked meanwhile
    next_run(settings)           the next time the schedule is due (UTC), or None (manual)
    status(user_id)              the GUI's view: schedule, next and last run, does the agent run for this user
    inbox_due(now) / inbox_ran   the worker's clock for the inbox owner (page_inbox.inbox_owner_id)

Mode `manual`: the agent runs only when asked (/next in Telegram, "Run now" in the app). Mode `scheduled`: every
`every_minutes`, or at the `times` of day, only on the `days` of the week, in the user's time zone (daylight saving
time included).

The next run counts from the latest of the last run, the last save and the last resume, so a run missed while the server was down is
made up once when it starts again (not once per missed time), and changing the schedule never fires a run at once.
With no saved schedule and no run yet, it counts from the server's start.

The worker asks every ~25 seconds (after each Telegram long poll), so a run starts within half a minute of its time.
The settings are cached for a minute; saving in the app updates the cache at once.
"""

import logging
import threading
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.core import config
from app.core.schemas import AutomationSchedule, AutomationSettings, AutomationStatus
from app.db import records

logger = logging.getLogger(__name__)

CACHE_SECONDS = 60
STARTED = datetime.now(UTC)  # reference for a schedule that never ran and was never saved

_lock = threading.Lock()
_cache: dict[str, tuple[datetime, AutomationSettings]] = {}  # user id → (read at, settings)
_ran: dict[str, datetime] = {}  # user id → last run kept in memory too (when the database could not be written)


# ---------- the settings ----------
def defaults() -> AutomationSchedule:
    """The schedule of a user who never saved one: every FACEBOOK_INBOX_INTERVAL minutes (0: manual)."""
    minutes = int(config.FACEBOOK_INBOX_INTERVAL)
    if minutes <= 0:
        return AutomationSchedule(mode="manual", times=["09:00"])
    return AutomationSchedule(mode="scheduled", every_minutes=max(15, minutes))


def schedule_of(user_id: str, fresh: bool = False) -> AutomationSettings:
    """The user's settings: saved, or the defaults (saved_at None). Cached for a minute unless `fresh`.

    Raises:
        DatabaseError: If the database cannot be read.
    """
    now = datetime.now(UTC)
    with _lock:
        cached = _cache.get(user_id)
    if cached and not fresh and (now - cached[0]).total_seconds() < CACHE_SECONDS:
        return cached[1]
    settings = records.get_automation_settings(user_id) or AutomationSettings(user_id=user_id,
                                                                              **defaults().model_dump())
    with _lock:
        _cache[user_id] = (now, settings)
    return settings


def save(user_id: str, schedule: AutomationSchedule) -> AutomationSettings:
    """Save the user's schedule (keeps the last run); the next run counts from now.

    Raises:
        DatabaseError: If the database cannot be read or written.
    """
    old = records.get_automation_settings(user_id)
    keep = old.model_dump(include={"last_run_at", "paused", "resumed_at"}) if old else {}
    settings = AutomationSettings(user_id=user_id, saved_at=datetime.now(UTC), **keep, **schedule.model_dump())
    records.save_automation_settings(settings)
    with _lock:
        _cache[user_id] = (datetime.now(UTC), settings)
    logger.info("A user saved the agent's schedule (%s)", describe(settings))
    return settings


def set_paused(user_id: str, paused: bool) -> AutomationSettings:
    """Pause or resume the user's schedule (the schedule itself is kept). Resuming counts the next run from now, so
    runs missed while paused do not fire at once.

    Raises:
        DatabaseError: If the database cannot be read or written.
    """
    settings = schedule_of(user_id, fresh=True)
    update = {"paused": paused, **({} if paused else {"resumed_at": datetime.now(UTC)})}
    settings = settings.model_copy(update=update)
    records.save_automation_settings(settings)
    with _lock:
        _cache[user_id] = (datetime.now(UTC), settings)
    logger.info("A user %s the agent's schedule", "paused" if paused else "resumed")
    return settings


def mark_run(user_id: str, now: datetime) -> None:
    """Remember that the agent ran for the user now (in the database; in memory if that fails)."""
    with _lock:
        _ran[user_id] = now
    try:
        settings = schedule_of(user_id, fresh=True)
        settings = settings.model_copy(update={"last_run_at": now})
        records.save_automation_settings(settings)
        with _lock:
            _cache[user_id] = (datetime.now(UTC), settings)
    except OSError as e:  # DatabaseError: the run is kept in memory, so it does not repeat every half minute
        logger.warning("Could not save the agent's last run: %s", e)


# ---------- the clock ----------
def reference(settings: AutomationSettings) -> datetime:
    """The time the next run counts from: the latest of the last run, save and resume (else the server's start)."""
    with _lock:
        in_memory = _ran.get(settings.user_id)
    times = [t for t in (settings.last_run_at, settings.saved_at, settings.resumed_at, in_memory) if t]
    return max(times) if times else STARTED


def next_run(settings: AutomationSettings, after: datetime | None = None) -> datetime | None:
    """The first time after `after` (default: reference(settings)) when the schedule is due, in UTC; None if manual."""
    return next_time(settings, after or reference(settings))


def next_time(schedule: AutomationSchedule, after: datetime) -> datetime | None:
    """The first scheduled time strictly after `after` (aware), in UTC; None if manual."""
    if schedule.mode != "scheduled":
        return None
    zone = ZoneInfo(schedule.timezone)
    local = after.astimezone(zone)
    if schedule.every_minutes:
        moment = after + timedelta(minutes=schedule.every_minutes)
        for _ in range(8):  # not on an allowed day: the start of the next allowed day
            day = moment.astimezone(zone).date()
            if day.weekday() in schedule.days:
                return moment.astimezone(UTC)
            moment = _at(day + timedelta(days=1), time(0, 0), zone)
        return None
    for offset in range(8):
        day = local.date() + timedelta(days=offset)
        if day.weekday() not in schedule.days:
            continue
        for hhmm in schedule.times:
            hours, minutes = (int(x) for x in hhmm.split(":"))
            moment = _at(day, time(hours, minutes), zone)
            if moment > after:
                return moment.astimezone(UTC)
    return None


def is_due(settings: AutomationSettings, now: datetime) -> bool:
    """True when the schedule's next run is at or before `now` (never while paused)."""
    if settings.paused:
        return False
    due = next_run(settings)
    return due is not None and due <= now


def _at(day: date, clock: time, zone: ZoneInfo) -> datetime:
    """That local time on that day, aware (a time skipped by daylight saving time moves forward)."""
    return datetime.combine(day, clock, tzinfo=zone).astimezone(UTC).astimezone(zone)


def describe(schedule: AutomationSchedule) -> str:
    """The schedule in words, e.g. "Mon–Fri at 09:00, 18:00 (Europe/Berlin)"."""
    if schedule.mode != "scheduled":
        return "manual (only when you ask)"
    names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    days = ("every day" if len(schedule.days) == 7 else "Mon–Fri" if schedule.days == [0, 1, 2, 3, 4]
            else ", ".join(names[d] for d in schedule.days))
    if schedule.every_minutes:
        every = schedule.every_minutes
        when = f"every {every // 60} h" if every % 60 == 0 else f"every {every} min"
    else:
        when = "at " + ", ".join(schedule.times)
    return f"{days} {when} ({schedule.timezone})"


# ---------- the inbox worker ----------
def inbox_owner() -> str | None:
    """The user the inbox worker runs for: the owner of the inbox books' client (None if not set up)."""
    from app.agents import page_inbox  # here: page_inbox is heavy (LangGraph) and imports the agents
    return page_inbox.inbox_owner_id()


def inbox_due(now: datetime) -> bool:
    """True when the inbox owner's schedule is due (False when there is no owner or the database fails)."""
    owner = inbox_owner()
    if not owner:
        return False
    try:
        return is_due(schedule_of(owner), now)
    except OSError as e:  # DatabaseError: try again on the next tick
        logger.warning("Could not read the agent's schedule: %s", e)
        return False


def inbox_ran(now: datetime) -> None:
    """Remember a run for the inbox owner."""
    if owner := inbox_owner():
        mark_run(owner, now)


def status(user_id: str) -> AutomationStatus:
    """The GUI's view of the user's schedule.

    Raises:
        DatabaseError: If the database cannot be read.
    """
    from app.agents import page_inbox_worker
    settings = schedule_of(user_id, fresh=True)
    schedule = AutomationSchedule(**settings.model_dump(include=set(AutomationSchedule.model_fields)))
    owner, running = inbox_owner(), page_inbox_worker.is_running()
    if not running:
        note = ("The agent is not running on the server: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID and "
                "FACEBOOK_INBOX_BOOKS must be set in server/.env.")
    elif owner != user_id:
        note = "The agent on this server works for the owner of other books; your schedule is saved but not used."
    else:
        note = ""
    with _lock:
        last = max((t for t in (settings.last_run_at, _ran.get(user_id)) if t), default=None)
    return AutomationStatus(schedule=schedule, saved=settings.saved_at is not None, paused=settings.paused,
                            next_run=None if settings.paused else next_run(settings), last_run=last,
                            active=running and owner == user_id, note=note)
