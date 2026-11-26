"""The red button: alarms to the admin's Telegram and the two app switches that stop things at once.

Switches (saved in private.app_switches, so a restart keeps them; records.load_switches):
    demo    the public demo ("Try as guest", core/guest.py) is on. Off: POST /guest and every guest request answer
            503 "The demo is paused". Switched off by hand (/demo_off in Telegram) or by the alarm itself.
    freeze  model calls are stopped for everyone except the admin (/freeze, /unfreeze): api/deps.py llm_limits.

Alarms (one Telegram message per kind at most once an hour, so an attack cannot flood the phone; without Telegram
they are only logged):
    spike     model costs of all users above [alarm] spike_usd within spike_minutes (limits.toml): the demo goes off
    takeover  the guest account's email was changed (someone tries to take it over): the demo goes off
    budget    a daily or monthly budget used up: the guest's, or the whole app's
    refusals  more than refusals_per_hour refused "Try as guest" (someone keeps trying)

Messages are sent in a background thread: an alarm never slows down or breaks the request that caused it.
"""

import logging
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone

from app.core import audit, guest
from app.core.limits import LIMITS
from app.db import records

logger = logging.getLogger(__name__)

THROTTLE = timedelta(hours=1)  # one message per kind at most this often
DEFAULTS = {"demo": True, "freeze": False}

_lock = threading.Lock()
_switches: dict[str, bool] = dict(DEFAULTS)
_last_sent: dict[str, datetime] = {}  # kind → when its last message went out
_costs: deque[tuple[float, float, bool]] = deque()  # (monotonic time, USD, by the guest) of recent model calls
_refusals: deque[float] = deque()  # monotonic times of refused "Try as guest"


# ---------- switches ----------
def load() -> None:
    """Read the saved switches (server start); a database error keeps the defaults and is logged."""
    try:
        saved = records.load_switches()
    except OSError as e:  # DatabaseError
        logger.error("Could not read the app switches, using the defaults: %s", e)
        return
    with _lock:
        _switches.update({name: on for name, on in saved.items() if name in DEFAULTS})
    if not _switches["demo"] or _switches["freeze"]:
        logger.warning("App switches on start: demo %s, freeze %s", _on(_switches["demo"]), _on(_switches["freeze"]))


def demo_on() -> bool:
    return _switches["demo"]


def frozen() -> bool:
    return _switches["freeze"]


def set_switch(name: str, on: bool, reason: str) -> bool:
    """Set a switch (in memory at once, then in the database). Returns False if it already was so.

    A database error is logged: the switch then holds until the server restarts.
    """
    with _lock:
        if _switches[name] == on:
            return False
        _switches[name] = on
    logger.warning("App switch %s → %s (%s)", name, _on(on), reason)
    audit.record("switch.changed", name, f"{_on(on)}: {reason}")
    try:
        records.save_switch(name, on, reason, datetime.now(timezone.utc))
    except OSError as e:  # DatabaseError
        logger.error("Could not save the app switch %s: %s", name, e)
    return True


def _on(on: bool) -> str:
    return "on" if on else "off"


# ---------- what the server reports ----------
def cost(usd: float, user_id: str | None, now: float | None = None) -> None:
    """One model call's cost (usage.record calls it for every call). Above spike_usd within spike_minutes: alarm,
    and the demo goes off."""
    if usd <= 0:
        return
    clock = time.monotonic() if now is None else now
    window = LIMITS.alarm.spike_minutes * 60
    by_guest = bool(user_id) and guest.is_guest(user_id or "", "")
    with _lock:
        _costs.append((clock, usd, by_guest))
        while _costs and clock - _costs[0][0] > window:
            _costs.popleft()
        total = sum(c for _, c, _ in _costs)
        of_guest = sum(c for _, c, g in _costs if g)
    if total < LIMITS.alarm.spike_usd:
        return
    switched = set_switch("demo", False, f"${total:.2f} spent in {LIMITS.alarm.spike_minutes} minutes")
    alert("spike", f"🚨 ${total:.2f} spent on model calls in the last {LIMITS.alarm.spike_minutes} minutes "
                   f"(the guest demo: ${of_guest:.2f})."
                   + (" I switched the guest demo off." if switched else "")
                   + "\n/demo_status for details · /demo_on to switch the demo on again · /freeze stops all model "
                     "calls except yours")


def takeover(email: str) -> None:
    """The guest account signed in with another email than GUEST_EMAIL: someone changed it. The demo goes off."""
    switched = set_switch("demo", False, "the guest account's email was changed")
    alert("takeover", "🚨 Someone changed the guest account's email (it is no longer the one in GUEST_EMAIL)."
                      + (" I switched the guest demo off." if switched else "")
                      + " The next “Try as guest” sets the email back once you switch the demo on (/demo_on).")


def budget(text: str) -> None:
    """A daily or monthly budget is used up (api/deps.py llm_limits)."""
    alert("budget:" + text, "⚠️ " + text)


def refused(now: float | None = None) -> None:
    """A "Try as guest" was refused (per-address or per-minute limit). More than refusals_per_hour: alarm."""
    clock = time.monotonic() if now is None else now
    with _lock:
        _refusals.append(clock)
        while _refusals and clock - _refusals[0] > 3600:
            _refusals.popleft()
        count = len(_refusals)
    if count > LIMITS.alarm.refusals_per_hour:
        alert("refusals", f"⚠️ Someone keeps trying to start the guest demo: {count} refusals in the last hour. "
                          "The limits hold; /demo_off pauses the demo completely.")


def recent(now: float | None = None) -> tuple[float, float, int]:
    """(USD of all users and USD of the guest within spike_minutes, refusals within the last hour)."""
    clock = time.monotonic() if now is None else now
    window = LIMITS.alarm.spike_minutes * 60
    with _lock:
        costs = [(c, g) for t, c, g in _costs if clock - t <= window]
        refusals = sum(1 for t in _refusals if clock - t <= 3600)
    return sum(c for c, _ in costs), sum(c for c, g in costs if g), refusals


# ---------- sending ----------
def alert(kind: str, text: str) -> None:
    """Tell the admin in Telegram, at most once an hour per kind; always logged."""
    now = datetime.now(timezone.utc)
    with _lock:
        last = _last_sent.get(kind)
        if last and now - last < THROTTLE:
            logger.info("Alarm %s (not sent again within the hour): %s", kind, text)
            return
        _last_sent[kind] = now
    logger.warning("Alarm %s: %s", kind, text)
    _dispatch(text)


def _dispatch(text: str) -> None:
    """Send in the background: a slow Telegram never holds up the request (tests replace this)."""
    threading.Thread(target=_send, args=(text,), name="alarm", daemon=True).start()


def _send(text: str) -> None:
    from app.social import telegram  # here: telegram is optional, and this module is imported early (usage.py)
    if not telegram.is_configured():
        return
    try:
        telegram.send_message(text)
    except Exception as e:  # noqa: BLE001 (an alarm must never fail loudly; it is in the log anyway)
        logger.error("Could not send the alarm to Telegram: %s", e)


def reset() -> None:
    """Forget everything (tests)."""
    with _lock:
        _switches.clear()
        _switches.update(DEFAULTS)
        _last_sent.clear()
        _costs.clear()
        _refusals.clear()
