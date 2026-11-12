"""The author's Telegram bot (Bot API): send them a message, read what they answer. The human-in-the-loop channel of
the Page inbox agent: it sends a proposed reply here and waits for "make it so", "skip" or feedback.

    bot_info()                              the bot's username (checks the token)
    send_message(text, buttons, reply_to)   a message to the author, optionally with buttons under it; long texts are
                                            split into several messages (the buttons go under the last)
    get_updates(offset, wait)               the author's new texts and button presses (long polling)
    answer_button(callback_id, text)        confirm a button press (stops the spinner, optional short notice)
    remove_buttons(message_id)              take the buttons off a message (a decided proposal is not pressed again)

Only the bot in TELEGRAM_BOT_TOKEN and only the private chat TELEGRAM_CHAT_ID (server/.env): messages go to that chat
alone, and updates from any other chat or sender are dropped (confirmed, so they do not come back) and logged without
their content. The Bot API puts the token in the URL path, so URLs are never logged (httpx's request log is silenced
in logs.py; errors are logged without str(e)). Texts are sent without parse_mode: third-party text quoted in a
proposal cannot turn into formatting or links.

Plain HTTP (httpx) next to the LangChain stack; no model call here. Errors are TelegramError with the HTTP status the
API should answer: 503 not configured / token invalid / bot blocked, 429 Telegram's rate limit, 502 any other Bot API
error, 504 timeout.
"""

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from app.core import config
from app.core.schemas import TelegramButton, TelegramUpdate, TelegramUpdates

logger = logging.getLogger(__name__)

API = "https://api.telegram.org"
TIMEOUT = 20  # seconds per request (a long poll gets its wait on top)
MAX_TEXT = 4096  # Telegram's limit for one message
MAX_WAIT = 50  # seconds a long poll may wait at most
MAX_BUTTON_DATA = 64  # bytes of a button's callback data


class TelegramError(Exception):
    """A Telegram request failed; status_code is the HTTP status the API should return."""

    def __init__(self, status_code: int, detail: str, retry_after: int | None = None):
        super().__init__(detail)
        self.status_code = status_code
        self.retry_after = retry_after  # seconds Telegram asks to wait (rate limit)


def is_configured() -> bool:
    """True if the bot token and the author's chat id are set in the configuration."""
    return bool(config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID is not None)


def bot_info() -> str:
    """The bot's username (without @); also checks that the token works."""
    return _request("getMe").get("username", "")


def send_message(text: str, buttons: list[TelegramButton] | None = None, reply_to: int | None = None) -> int:
    """Send a text to the author's chat. A text over MAX_TEXT characters goes as several messages.

    Args:
        text: Plain text (no formatting).
        buttons: Buttons in one row under the (last) message.
        reply_to: A message in the chat this one answers (shown quoted above it).

    Returns:
        The id of the (last) message sent: the one the buttons are under.

    Raises:
        ValueError: If the text is empty or a button's data is empty or too long.
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("The text is empty.")
    markup = _keyboard(buttons) if buttons else None
    parts = split_text(text)
    message_id = 0
    for i, part in enumerate(parts):
        body: dict[str, Any] = {"chat_id": config.TELEGRAM_CHAT_ID, "text": part, "link_preview_options": {
            "is_disabled": True}}
        if reply_to and i == 0:
            body["reply_parameters"] = {"message_id": reply_to, "allow_sending_without_reply": True}
        if markup and i == len(parts) - 1:
            body["reply_markup"] = markup
        message_id = _request("sendMessage", body)["message_id"]
    return message_id


def get_updates(offset: int | None = None, wait: int = 0) -> TelegramUpdates:
    """The author's new texts and button presses, oldest first.

    Passing the previous `next_offset` confirms everything before it: Telegram then no longer returns it. Updates from
    other chats or senders, and kinds of update the agent does not use (photos, edits, ...), are left out but still
    confirmed.

    Args:
        offset: The previous call's next_offset (None: everything Telegram still holds, up to 24 hours).
        wait: Seconds to wait for a new update when there is none yet (long polling, 0-50).
    """
    wait = max(0, min(wait, MAX_WAIT))
    body: dict[str, Any] = {"timeout": wait, "allowed_updates": ["message", "callback_query"]}
    if offset is not None:
        body["offset"] = offset
    raw = _request("getUpdates", body, timeout=TIMEOUT + wait)
    items, next_offset = [], offset
    for update in raw:
        next_offset = update["update_id"] + 1
        item = _update(update)
        if item:
            items.append(item)
    return TelegramUpdates(items=items, next_offset=next_offset)


def answer_button(callback_id: str, text: str | None = None) -> None:
    """Confirm a button press so Telegram stops showing it as loading; `text` shows as a short notice. A press that is
    too old to confirm (Telegram allows only a short time, e.g. after a server restart) is skipped: the press itself
    still counts."""
    body: dict[str, Any] = {"callback_query_id": callback_id}
    if text:
        body["text"] = text[:200]
    try:
        _request("answerCallbackQuery", body)
    except TelegramError as e:
        if "query is too old" not in str(e) and "query ID is invalid" not in str(e):
            raise


def remove_buttons(message_id: int) -> None:
    """Take the buttons off a bot message in the author's chat. A message that has none already is fine."""
    try:
        _request("editMessageReplyMarkup", {"chat_id": config.TELEGRAM_CHAT_ID, "message_id": message_id,
                                            "reply_markup": {"inline_keyboard": []}})
    except TelegramError as e:
        if "not modified" not in str(e):
            raise


def split_text(text: str, limit: int = MAX_TEXT) -> list[str]:
    """The text in parts of at most `limit` characters, cut at a paragraph, else a line, else a space if possible."""
    parts = []
    while len(text) > limit:
        cut = max(text.rfind(sep, 0, limit + 1) for sep in ("\n\n", "\n", " "))
        if cut <= limit // 2:  # no good break in the second half: cut hard
            cut = limit
        parts.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    if text:
        parts.append(text)
    return parts


# ---------- helpers ----------
def _client(timeout: float) -> httpx.Client:
    """The HTTP client for Bot API requests (tests replace it with one on a fake transport)."""
    return httpx.Client(timeout=timeout)


def _request(method: str, body: dict[str, Any] | None = None, timeout: float = TIMEOUT) -> Any:
    """One Bot API call; its `result`, or TelegramError. The method name is logged, never the URL (it holds the
    token)."""
    if not is_configured():
        raise TelegramError(503, "Telegram is not connected: set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in "
                                 "server/.env and restart the server.")
    try:
        with _client(timeout) as client:
            # a full URL: "bot<id>:<secret>" alone would be read as a URL with the scheme "bot<id>:"
            response = client.post(f"{API}/bot{config.TELEGRAM_BOT_TOKEN}/{method}", json=body or {})
    except httpx.TimeoutException as e:
        raise TelegramError(504, "Telegram did not answer in time. Try again.") from e
    except httpx.HTTPError as e:  # no str(e): it can contain the URL and with it the token
        logger.warning("Telegram %s failed: %s", method, type(e).__name__)
        raise TelegramError(502, "Could not reach Telegram. Try again.") from e
    try:
        data = response.json()
    except ValueError:
        data = {}
    if response.is_success and data.get("ok"):
        return data.get("result")
    raise _error(data, response.status_code, method)


def _error(data: dict[str, Any], http_status: int, method: str) -> TelegramError:
    """TelegramError for a Bot API error answer, with a status and a message the author can act on."""
    code = data.get("error_code") or http_status
    description = data.get("description") or f"HTTP {http_status}"
    logger.warning("Telegram %s: error %s: %s", method, code, description)
    if code in (401, 404):  # 404 = the token's bot does not exist
        return TelegramError(503, "The Telegram bot token is invalid: copy it again from @BotFather (/mybots → your "
                                  "bot → API Token) and restart the server.")
    if code == 403:
        return TelegramError(503, "Telegram refuses to deliver: open your bot in Telegram, press Start (or unblock "
                                  "it) and check TELEGRAM_CHAT_ID.")
    if code == 429:
        retry = (data.get("parameters") or {}).get("retry_after")
        return TelegramError(429, "Telegram's rate limit is reached. Try again shortly.", retry_after=retry)
    return TelegramError(502, f"Telegram answered with an error: {description}")


def _keyboard(buttons: list[TelegramButton]) -> dict[str, Any]:
    """Inline keyboard markup: the buttons in one row."""
    for b in buttons:
        if not b.label.strip() or not b.data or len(b.data.encode()) > MAX_BUTTON_DATA:
            raise ValueError(f"A button needs a label and data of 1-{MAX_BUTTON_DATA} bytes.")
    return {"inline_keyboard": [[{"text": b.label, "callback_data": b.data} for b in buttons]]}


def _update(update: dict[str, Any]) -> TelegramUpdate | None:
    """A Bot API update as TelegramUpdate, or None when it is not a text or button press by the author in their chat."""
    if message := update.get("message"):
        if not _from_author(message.get("chat"), message.get("from")) or "text" not in message:
            return _dropped(update, "message")
        return TelegramUpdate(
            update_id=update["update_id"], kind="text", text=message["text"], message_id=message["message_id"],
            reply_to_message_id=(message.get("reply_to_message") or {}).get("message_id"),
            date=_date(message.get("date")))
    if query := update.get("callback_query"):
        message = query.get("message") or {}
        if not _from_author(message.get("chat"), query.get("from")):
            return _dropped(update, "button press")
        return TelegramUpdate(
            update_id=update["update_id"], kind="button", text=query.get("data", ""),
            message_id=message.get("message_id", 0), callback_id=query["id"], date=_date(message.get("date")))
    return None


def _from_author(chat: dict[str, Any] | None, sender: dict[str, Any] | None) -> bool:
    """True if the update comes from the author: their private chat with the bot, sent by them."""
    author = config.TELEGRAM_CHAT_ID
    return bool(chat and sender) and chat.get("id") == author and sender.get("id") == author


def _dropped(update: dict[str, Any], what: str) -> None:
    """Log (without content) an update that is not from the author or not text, and drop it."""
    message = update.get("message") or (update.get("callback_query") or {}).get("message") or {}
    chat_id = (message.get("chat") or {}).get("id")
    if chat_id != config.TELEGRAM_CHAT_ID:
        logger.warning("Telegram: ignored a %s from another chat (%s)", what, chat_id)
    return None


def _date(timestamp: int | None) -> datetime:
    """A Telegram Unix timestamp as an aware datetime (now if missing)."""
    return datetime.fromtimestamp(timestamp, timezone.utc) if timestamp else datetime.now(timezone.utc)
