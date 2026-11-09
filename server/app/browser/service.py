"""The browser service: a visible Chromium (Playwright) the server uses to read pages of platforms like Reddit with a
login the author makes in the browser window. It knows nothing about any platform; the platform plug-ins (adapters/) decide which
pages to open and what to read from them.

    service.run("reddit", work)     work(session) runs on a new tab of the platform's browser window;
                                    session.goto(url) loads a page at a human pace and stops on CAPTCHAs
    service.open_login("reddit", url)   opens the login page and leaves it open for the author

Rules, the same for every platform:
  • One login profile (cookies) per platform in BROWSER_PROFILE_DIR/<platform>, git-ignored. The author logs in in the
    window; the app never sees or stores a password. delete_profile() is the logout.
  • Visible window (headless=False), read-only use, a human pace: at least MIN_INTERVAL seconds between page loads
    and at most MAX_PER_HOUR loads per hour, per platform.
  • A CAPTCHA or "are you human" page stops the work with Challenge. No stealth: the browser is a normal Chromium and
    never tries to hide that it is automated or to get around such checks.
  • Only code drives the browser; no model or agent gets it as a tool.

Threading: Playwright objects belong to the event loop that created them. FastAPI runs sync routes in a thread pool,
so the service owns one background thread with its own asyncio loop; run() hands work to it and waits. One tab at a
time per platform (a lock); a window unused for IDLE_CLOSE seconds is closed (the login stays in the profile).
"""

import asyncio
import logging
import re
import shutil
import threading
import time
from collections import deque
from collections.abc import Awaitable, Callable
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

from app.browser.errors import (
    Blocked, BrowserClosed, BrowserDisabled, BrowserError, BrowserTimeout, Challenge, RateLimited, UnknownPlatform,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")

MIN_INTERVAL = 4.0  # seconds between two page loads of one platform
MAX_PER_HOUR = 60  # page loads per platform and hour
PAGE_TIMEOUT = 30.0  # seconds a page may take to load
RUN_TIMEOUT = 120.0  # seconds one piece of work may take in total
IDLE_CLOSE = 300.0  # seconds after which an unused window is closed
LOGIN_IDLE_CLOSE = 900.0  # the same while a login page was opened for the author
VIEWPORT = {"width": 1280, "height": 900}

_PLATFORM = re.compile(r"^[a-z][a-z0-9_]{1,30}$")  # also the profile folder's name: no paths
# Signs of a CAPTCHA or human check, for any site: the frames of the common services, and typical page titles.
CHALLENGE_SELECTORS = ('iframe[src*="recaptcha"]', 'iframe[src*="hcaptcha"]', 'iframe[src*="challenges.cloudflare"]',
                       'iframe[src*="arkoselabs"]', "#challenge-form", "#cf-challenge-running")
CHALLENGE_TITLES = re.compile(r"just a moment|verify (that )?you are (a )?human|are you a robot|security check|"
                              r"attention required|access denied", re.IGNORECASE)

# Launches a persistent browser context: (profile folder, headless?) -> context. Replaced by a fake in tests.
Launcher = Callable[[Path, bool], Awaitable[Any]]


@dataclass
class Session:
    """One piece of work on a platform: a new tab, and goto() that keeps the platform's pace and checks for CAPTCHAs."""

    platform: str
    page: Any  # playwright Page
    _service: "BrowserService"

    async def goto(self, url: str) -> Any:
        """Load a page (waiting for the platform's pace first). Returns the response.

        Raises:
            RateLimited, Blocked (HTTP 403/429), Challenge, BrowserTimeout, BrowserClosed.
        """
        return await self._service._goto(self, url)


@dataclass
class _Platform:
    """The service's state for one platform."""

    context: Any = None  # playwright BrowserContext while the window is open
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    last_load: float | None = None  # clock time of the last page load
    loads: deque = field(default_factory=deque)  # clock times of the page loads in the last hour
    last_used: float = 0.0
    login_open: bool = False  # a login page was opened for the author: close the window later


class BrowserService:
    """See the module docstring. One instance per server (get_service())."""

    def __init__(self, profile_dir: Path, *, launcher: Launcher | None = None, headless: bool = False,
                 min_interval: float = MIN_INTERVAL, max_per_hour: int = MAX_PER_HOUR,
                 page_timeout: float = PAGE_TIMEOUT, idle_close: float = IDLE_CLOSE,
                 clock: Callable[[], float] = time.monotonic):
        self.profile_dir = Path(profile_dir)
        self.headless = headless
        self.min_interval, self.max_per_hour = min_interval, max_per_hour
        self.page_timeout, self.idle_close = page_timeout, idle_close
        self._clock = clock
        self._launcher = launcher
        self._playwright: Any = None
        self._platforms: dict[str, _Platform] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._start_lock = threading.Lock()
        self._janitor: asyncio.Task | None = None

    # ---------- public API (any thread) ----------
    def run(self, platform: str, work: Callable[[Session], Awaitable[T]], timeout: float = RUN_TIMEOUT) -> T:
        """Run work(session) on a new tab of the platform's browser window and return its result. The tab is closed
        afterwards; the window stays open for the next work until it is idle.

        Raises:
            UnknownPlatform: For a platform name that is not a simple lowercase name.
            BrowserError: Whatever the page loads or the work raise (see Session.goto); BrowserTimeout when the whole
                work takes longer than `timeout`.
        """
        _check_name(platform)
        return self._call(self._run(platform, work), timeout)

    def open_login(self, platform: str, url: str) -> None:
        """Open the platform's login page in its window and leave it open for the author to log in."""
        _check_name(platform)
        self._call(self._open_login(platform, url), RUN_TIMEOUT)

    def has_profile(self, platform: str) -> bool:
        """True when the platform has a saved profile (it was used or logged in before)."""
        _check_name(platform)
        return (self.profile_dir / platform).is_dir()

    def is_open(self, platform: str) -> bool:
        """True while the platform's browser window is open."""
        state = self._platforms.get(platform)
        return bool(state and state.context)

    def close(self, platform: str) -> None:
        """Close the platform's window (the login stays in its profile)."""
        _check_name(platform)
        if self._loop:
            self._call(self._close(platform), RUN_TIMEOUT)

    def delete_profile(self, platform: str) -> None:
        """Log out: close the platform's window and delete its profile with the login cookies."""
        self.close(platform)
        shutil.rmtree(self.profile_dir / platform, ignore_errors=True)
        self._platforms.pop(platform, None)

    def shutdown(self) -> None:
        """Close every window and stop the background thread (server shutdown)."""
        if not self._loop:
            return
        try:
            self._call(self._shutdown(), RUN_TIMEOUT)
        finally:
            self._loop.call_soon_threadsafe(self._loop.stop)
            if self._thread:
                self._thread.join(timeout=10)
            self._loop = self._thread = None

    # ---------- the background loop ----------
    def _call(self, coro: Awaitable[T], timeout: float) -> T:
        """Run a coroutine on the service's loop and wait for its result."""
        loop = self._ensure_loop()
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        try:
            return future.result(timeout)
        except FutureTimeout as e:
            future.cancel()
            raise BrowserTimeout("The browser did not finish in time.") from e

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        with self._start_lock:
            if self._loop is None:
                loop = asyncio.new_event_loop()
                ready = threading.Event()

                def serve() -> None:
                    asyncio.set_event_loop(loop)
                    loop.call_soon(ready.set)
                    loop.run_forever()
                    loop.close()

                self._thread = threading.Thread(target=serve, name="browser-service", daemon=True)
                self._thread.start()
                ready.wait()
                self._loop = loop
                asyncio.run_coroutine_threadsafe(self._start_janitor(), loop).result()
            return self._loop

    async def _start_janitor(self) -> None:
        self._janitor = asyncio.create_task(self._close_idle_windows())

    async def _close_idle_windows(self) -> None:
        """Every 30 seconds: close windows that were not used for a while (longer while a login page is open)."""
        while True:
            await asyncio.sleep(30)
            now = self._clock()
            for name, state in list(self._platforms.items()):
                limit = LOGIN_IDLE_CLOSE if state.login_open else self.idle_close
                if state.context and not state.lock.locked() and now - state.last_used > limit:
                    logger.info("Closing the idle %s browser window", name)
                    await self._close(name)

    # ---------- on the loop ----------
    def _state(self, platform: str) -> _Platform:
        return self._platforms.setdefault(platform, _Platform())

    async def _launch(self, profile: Path) -> Any:
        if self._launcher:
            return await self._launcher(profile, self.headless)
        if self._playwright is None:
            try:
                from playwright.async_api import async_playwright
            except ImportError as e:
                raise BrowserDisabled("Playwright is not installed: run `uv sync` in server/.") from e
            self._playwright = await async_playwright().start()
        try:
            return await self._playwright.chromium.launch_persistent_context(
                str(profile), headless=self.headless, viewport=VIEWPORT)
        except Exception as e:
            if "Executable doesn't exist" in str(e):
                raise BrowserDisabled("Chromium is not installed: run `uv run playwright install chromium` in "
                                      "server/.") from e
            raise BrowserError(f"The browser could not start: {e}") from e

    async def _context(self, platform: str) -> Any:
        """The platform's open window, started with its profile when needed."""
        state = self._state(platform)
        if state.context is None:
            profile = self.profile_dir / platform
            profile.mkdir(parents=True, exist_ok=True)
            context = await self._launch(profile)
            context.on("close", lambda *_: self._forget(platform, context))  # e.g. the author closed the window
            state.context = context
        state.last_used = self._clock()
        return state.context

    def _forget(self, platform: str, context: Any) -> None:
        state = self._platforms.get(platform)
        if state and state.context is context:
            state.context, state.login_open = None, False

    async def _run(self, platform: str, work: Callable[[Session], Awaitable[T]]) -> T:
        state = self._state(platform)
        async with state.lock:
            context = await self._context(platform)
            try:
                page = await context.new_page()
            except Exception as e:
                self._forget(platform, context)
                raise BrowserClosed("The browser window was closed. Please try again.") from e
            try:
                return await work(Session(platform, page, self))
            except BrowserError:
                raise
            except Exception as e:
                if _closed(e):
                    raise BrowserClosed("The browser window was closed while reading the page.") from e
                if _timed_out(e):
                    raise BrowserTimeout("The page did not load in time.") from e
                raise
            finally:
                state.last_used = self._clock()
                try:
                    await page.close()
                except Exception:  # already closed with the window
                    pass

    async def _open_login(self, platform: str, url: str) -> None:
        state = self._state(platform)
        async with state.lock:
            context = await self._context(platform)
            page = await context.new_page()
            await self._goto(Session(platform, page, self), url, check_challenge=False)  # the author handles any check
            await page.bring_to_front()
            state.login_open = True

    async def _goto(self, session: Session, url: str, check_challenge: bool = True) -> Any:
        state = self._state(session.platform)
        await self._keep_pace(session.platform, state)
        try:
            response = await session.page.goto(url, wait_until="domcontentloaded", timeout=self.page_timeout * 1000)
        except Exception as e:
            if _timed_out(e):
                raise BrowserTimeout(f"The page did not load within {self.page_timeout:.0f} seconds.") from e
            if _closed(e):
                raise BrowserClosed("The browser window was closed while loading the page.") from e
            raise BrowserError(f"The page could not be loaded: {e}") from e
        status = getattr(response, "status", 200) if response is not None else 200
        if check_challenge and await is_challenge(session.page):
            raise Challenge("The site asks for a human check (CAPTCHA). Solve it in the browser window and try "
                            "again, or open the page yourself and paste the text.")
        if status in (403, 429):
            raise Blocked(f"The site refused the page (HTTP {status}).")
        return response

    async def _keep_pace(self, platform: str, state: _Platform) -> None:
        """Wait until MIN_INTERVAL has passed since the platform's last page load; refuse beyond MAX_PER_HOUR."""
        now = self._clock()
        while state.loads and now - state.loads[0] > 3600:
            state.loads.popleft()
        if len(state.loads) >= self.max_per_hour:
            minutes = int((3600 - (now - state.loads[0])) // 60) + 1
            raise RateLimited(f"The app's limit of {self.max_per_hour} pages per hour for {platform} is reached. "
                              f"Try again in about {minutes} minutes.")
        if state.last_load is not None and (wait := self.min_interval - (now - state.last_load)) > 0:
            await asyncio.sleep(wait)
        state.last_load = self._clock()
        state.loads.append(state.last_load)

    async def _close(self, platform: str) -> None:
        state = self._platforms.get(platform)
        if state and state.context:
            context, state.context, state.login_open = state.context, None, False
            try:
                await context.close()
            except Exception:  # already closed
                pass

    async def _shutdown(self) -> None:
        if self._janitor:
            self._janitor.cancel()
        for name in list(self._platforms):
            await self._close(name)
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None


async def is_challenge(page: Any) -> bool:
    """True when the page looks like a CAPTCHA or "are you human" check (any site)."""
    try:
        if CHALLENGE_TITLES.search(await page.title() or ""):
            return True
        for selector in CHALLENGE_SELECTORS:
            if await page.locator(selector).count():
                return True
    except Exception:  # a page that navigates away while being checked
        return False
    return False


def _check_name(platform: str) -> None:
    if not _PLATFORM.match(platform or ""):
        raise UnknownPlatform(f"'{platform}' is not a platform name.")


def _timed_out(e: Exception) -> bool:
    return type(e).__name__ == "TimeoutError" or "Timeout" in type(e).__name__


def _closed(e: Exception) -> bool:
    return "closed" in str(e).lower() and ("target" in str(e).lower() or "browser" in str(e).lower())


# ---------- the server's service ----------
_service: BrowserService | None = None
_service_lock = threading.Lock()


def get_service() -> BrowserService:
    """The server's browser service, created on first use.

    Raises:
        BrowserDisabled: When BROWSER_AUTOMATION is off.
    """
    from app.core import config

    global _service
    if not config.BROWSER_AUTOMATION:
        raise BrowserDisabled("Reading pages in the browser is switched off. Set BROWSER_AUTOMATION=on in "
                              "server/.env and restart the server (only on your own computer).")
    with _service_lock:
        if _service is None:
            _service = BrowserService(config.BROWSER_PROFILE_DIR)
        return _service


def shutdown_service() -> None:
    """Close the browser at server shutdown (no-op when it was never used)."""
    global _service
    with _service_lock:
        if _service is not None:
            _service.shutdown()
            _service = None
