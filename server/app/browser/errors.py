"""Errors of the browser layer. Each says what happened in words for the author; the API (step 5) maps them to HTTP
status codes. All derive from BrowserError, so a caller can fall back (e.g. "open the thread and paste it") on any."""


class BrowserError(Exception):
    """Something went wrong reading a page in the browser."""


class BrowserDisabled(BrowserError):
    """Browser automation is switched off (BROWSER_AUTOMATION) or Playwright/Chromium is not installed."""


class UnknownPlatform(BrowserError):
    """No platform plug-in handles this platform name or URL."""


class NotLoggedIn(BrowserError):
    """The platform needs a login in the app's browser first (Settings → Connected platforms)."""


class Challenge(BrowserError):
    """The site shows a CAPTCHA or "are you human" check. The browser stops; the author can solve it in the window or
    paste the text instead. The app never tries to get around such checks."""


class Blocked(BrowserError):
    """The site refused the page (e.g. HTTP 403 or 429)."""


class RateLimited(BrowserError):
    """The app's own limit of page loads per hour for this platform is reached (to stay at a human pace)."""


class BrowserTimeout(BrowserError):
    """The page did not load in time."""


class BrowserClosed(BrowserError):
    """The browser window was closed while it was in use."""
