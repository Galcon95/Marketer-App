"""Browser service (app/browser/service.py): pace and hourly limit, CAPTCHA and refused pages, one window per platform
that is reopened after the author closes it, login profiles, and the switch. A fake browser stands in for Chromium;
one test at the end uses the real Chromium (headless, a local page only) and is skipped when it is not installed."""

import time

import pytest

from app.browser import service as svc
from app.browser.errors import (
    Blocked, BrowserClosed, BrowserDisabled, BrowserTimeout, Challenge, RateLimited, UnknownPlatform,
)
from app.core import config


class FakeResponse:
    def __init__(self, status):
        self.status = status


class FakeLocator:
    def __init__(self, n):
        self.n = n

    async def count(self):
        return self.n


class TimeoutError(Exception):  # named like Playwright's, which the service recognises by name
    pass


class FakePage:
    def __init__(self, browser):
        self.browser, self.url, self.closed, self.front = browser, "about:blank", False, False

    async def goto(self, url, wait_until, timeout):
        self.browser.loads.append((url, time.monotonic()))
        page = self.browser.pages.get(url, {})
        if page.get("timeout"):
            raise TimeoutError("Timeout 30000ms exceeded")
        self.url = url
        return FakeResponse(page.get("status", 200))

    async def title(self):
        return self.browser.pages.get(self.url, {}).get("title", "A page")

    def locator(self, selector):
        return FakeLocator(1 if selector in self.browser.pages.get(self.url, {}).get("frames", ()) else 0)

    async def bring_to_front(self):
        self.front = True

    async def close(self):
        self.closed = True


class FakeContext:
    def __init__(self, browser, profile):
        self.browser, self.profile, self.closed, self.handlers = browser, profile, False, []

    def on(self, event, handler):
        assert event == "close"
        self.handlers.append(handler)

    async def new_page(self):
        if self.closed:
            raise RuntimeError("Target page, context or browser has been closed")
        page = FakePage(self.browser)
        self.browser.opened.append(page)
        return page

    async def close(self):
        self.closed = True

    def closed_by_author(self):
        self.closed = True
        for handler in self.handlers:
            handler(self)


class FakeBrowser:
    """Records launches and page loads; `pages` sets what a URL answers (status, title, frames, timeout)."""

    def __init__(self):
        self.launches, self.loads, self.opened, self.pages = [], [], [], {}

    async def launch(self, profile, headless):
        context = FakeContext(self, profile)
        self.launches.append((profile, headless, context))
        return context


@pytest.fixture
def browser():
    return FakeBrowser()


@pytest.fixture
def service(tmp_path, browser):
    s = svc.BrowserService(tmp_path / "profiles", launcher=browser.launch, min_interval=0.0, max_per_hour=100)
    yield s
    s.shutdown()


async def _url(session):
    await session.goto("https://example.com/thread")
    return session.page.url


# ---------- running work ----------
def test_work_runs_on_a_new_tab_that_is_closed_afterwards(service, browser):
    assert service.run("reddit", _url) == "https://example.com/thread"
    assert browser.opened[0].closed and service.is_open("reddit")
    profile, headless, _ = browser.launches[0]
    assert profile.name == "reddit" and profile.is_dir() and headless is False  # visible window, own profile


def test_one_window_per_platform_reused_between_runs(service, browser):
    service.run("reddit", _url)
    service.run("reddit", _url)
    service.run("facebook", _url)
    assert [p.name for p, _, _ in browser.launches] == ["reddit", "facebook"]


def test_a_window_closed_by_the_author_is_opened_again(service, browser):
    service.run("reddit", _url)
    browser.launches[0][2].closed_by_author()
    assert not service.is_open("reddit")
    assert service.run("reddit", _url) == "https://example.com/thread"
    assert len(browser.launches) == 2


def test_errors_of_the_work_itself_reach_the_caller(service):
    async def broken(session):
        raise ValueError("parser failed")
    with pytest.raises(ValueError):
        service.run("reddit", broken)


@pytest.mark.parametrize("name", ["Reddit", "../etc", "", "a" * 40, "red dit"])
def test_platform_names_cannot_be_paths(service, name):
    with pytest.raises(UnknownPlatform):
        service.run(name, _url)


# ---------- pace and limits ----------
def test_page_loads_keep_the_minimum_interval(tmp_path, browser):
    s = svc.BrowserService(tmp_path, launcher=browser.launch, min_interval=0.3)
    try:
        s.run("reddit", _url)
        s.run("reddit", _url)
        s.run("facebook", _url)  # another platform has its own pace
    finally:
        s.shutdown()
    (_, t1), (_, t2), (_, t3) = browser.loads
    assert t2 - t1 >= 0.29 and t3 - t2 < 0.25


def test_the_hourly_limit_refuses_further_loads(tmp_path, browser):
    s = svc.BrowserService(tmp_path, launcher=browser.launch, min_interval=0.0, max_per_hour=2)
    try:
        s.run("reddit", _url)
        s.run("reddit", _url)
        with pytest.raises(RateLimited, match="2 pages per hour"):
            s.run("reddit", _url)
        assert len(browser.loads) == 2
        s.run("facebook", _url)  # counted per platform
    finally:
        s.shutdown()


# ---------- what pages answer ----------
@pytest.mark.parametrize("page", [
    {"title": "Just a moment..."},
    {"title": "Reddit - Please verify you are a human"},
    {"frames": ['iframe[src*="recaptcha"]']},
    {"frames": ['iframe[src*="challenges.cloudflare"]']},
])
def test_a_captcha_stops_the_work(service, browser, page):
    browser.pages["https://example.com/thread"] = page
    with pytest.raises(Challenge, match="human check"):
        service.run("reddit", _url)


@pytest.mark.parametrize("status", [403, 429])
def test_a_refused_page_is_blocked(service, browser, status):
    browser.pages["https://example.com/thread"] = {"status": status}
    with pytest.raises(Blocked, match=str(status)):
        service.run("reddit", _url)


def test_a_slow_page_is_a_timeout(service, browser):
    browser.pages["https://example.com/thread"] = {"timeout": True}
    with pytest.raises(BrowserTimeout):
        service.run("reddit", _url)


def test_work_on_a_closed_window_is_reported(service, browser):
    service.run("reddit", _url)
    browser.launches[0][2].closed = True  # closed, but the close event has not arrived yet
    with pytest.raises(BrowserClosed):
        service.run("reddit", _url)
    assert service.run("reddit", _url) == "https://example.com/thread"  # the next run opens a new window


# ---------- login and logout ----------
def test_login_page_stays_open_for_the_author(service, browser):
    browser.pages["https://www.reddit.com/login"] = {"title": "Just a moment..."}  # the author handles any check
    service.open_login("reddit", "https://www.reddit.com/login")
    page = browser.opened[0]
    assert page.url == "https://www.reddit.com/login" and page.front and not page.closed


def test_delete_profile_logs_out(service, browser):
    service.run("reddit", _url)
    assert service.has_profile("reddit")
    service.delete_profile("reddit")
    assert not service.has_profile("reddit") and not service.is_open("reddit")
    assert browser.launches[0][2].closed


# ---------- the switch ----------
def test_switched_off_there_is_no_service(monkeypatch):
    monkeypatch.setattr(config, "BROWSER_AUTOMATION", False)
    with pytest.raises(BrowserDisabled, match="BROWSER_AUTOMATION=on"):
        svc.get_service()


# ---------- the real browser ----------
def test_real_chromium_reads_a_local_page(tmp_path):
    """Headless and offline: a data: URL. Skipped when Playwright's Chromium is not installed."""
    s = svc.BrowserService(tmp_path, headless=True, min_interval=0.0)

    async def read(session):
        await session.goto("data:text/html,<title>Check</title><h1>Hello from Chromium</h1>")
        return await session.page.title(), await session.page.inner_text("h1")
    try:
        assert s.run("check", read) == ("Check", "Hello from Chromium")
    except BrowserDisabled as e:
        pytest.skip(str(e))
    finally:
        s.shutdown()
