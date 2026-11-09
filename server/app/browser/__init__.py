"""Browser layer: a visible Chromium (Playwright) for reading platforms with logins the author makes in the browser window.

service.py   the browser, platform-neutral (pacing, CAPTCHA stop, one login profile per platform)
errors.py    what can go wrong, for fallbacks and HTTP status codes
adapters/    one plug-in per platform (Reddit first), added in step 3
"""
