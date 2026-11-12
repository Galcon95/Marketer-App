"""Telegram bot client (social/telegram.py): requests it sends, which updates reach the agent (only the author's
chat), message splitting, buttons and error mapping. The Bot API is faked with an httpx MockTransport; nothing leaves
the machine."""

import json

import httpx
import pytest

from app.core import config
from app.core.schemas import TelegramButton
from app.social import telegram as tg

TOKEN = "123456:ABC-test-token"
AUTHOR = 424242
STRANGER = 555


@pytest.fixture
def bot(monkeypatch):
    """Configure the bot and route Bot API requests to a fake. Set `bot.answer` (a result, or (status, full body)),
    or `bot.answers` (a list, one per request); the requests sent are in `bot.requests`."""
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", AUTHOR)

    class Fake:
        answer: object = True
        answers: list | None = None
        requests: list[httpx.Request] = []
        error: Exception | None = None
        timeouts: list = []

    fake = Fake()
    fake.requests, fake.timeouts = [], []

    def handler(request: httpx.Request) -> httpx.Response:
        fake.requests.append(request)
        if fake.error:
            raise fake.error
        answer = fake.answers.pop(0) if fake.answers else fake.answer
        if isinstance(answer, tuple):
            return httpx.Response(answer[0], json=answer[1])
        return httpx.Response(200, json={"ok": True, "result": answer})

    def client(timeout):
        fake.timeouts.append(timeout)
        return httpx.Client(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(tg, "_client", client)
    return fake


def _body(request: httpx.Request) -> dict:
    return json.loads(request.content)


def _method(request: httpx.Request) -> str:
    return request.url.path.rsplit("/", 1)[-1]


def _text_update(update_id, text, chat=AUTHOR, sender=AUTHOR, reply_to=None):
    message = {"message_id": 100 + update_id, "date": 1_700_000_000, "chat": {"id": chat, "type": "private"},
               "from": {"id": sender}, "text": text}
    if reply_to:
        message["reply_to_message"] = {"message_id": reply_to}
    return {"update_id": update_id, "message": message}


def _button_update(update_id, data, chat=AUTHOR, sender=AUTHOR):
    return {"update_id": update_id, "callback_query": {
        "id": f"cb{update_id}", "from": {"id": sender}, "data": data,
        "message": {"message_id": 42, "date": 1_700_000_000, "chat": {"id": chat}}}}


# ---------- configuration ----------
def test_not_configured_is_503_without_a_request(bot, monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", None)
    assert not tg.is_configured()
    with pytest.raises(tg.TelegramError) as e:
        tg.send_message("hi")
    assert e.value.status_code == 503
    assert bot.requests == []


def test_bot_info_calls_getme_with_the_token_in_the_path(bot):
    bot.answer = {"id": 1, "username": "haic_marketer_bot"}
    assert tg.bot_info() == "haic_marketer_bot"
    assert str(bot.requests[0].url) == f"https://api.telegram.org/bot{TOKEN}/getMe"


# ---------- sending ----------
def test_send_message_goes_to_the_authors_chat_as_plain_text(bot):
    bot.answer = {"message_id": 7}
    assert tg.send_message("  Hello  ") == 7
    body = _body(bot.requests[0])
    assert _method(bot.requests[0]) == "sendMessage"
    assert body["chat_id"] == AUTHOR
    assert body["text"] == "Hello"
    assert "parse_mode" not in body  # quoted third-party text cannot become formatting
    assert body["link_preview_options"] == {"is_disabled": True}
    assert "reply_markup" not in body and "reply_parameters" not in body


def test_send_message_with_buttons_and_reply(bot):
    bot.answer = {"message_id": 8}
    tg.send_message("Proposal", buttons=[TelegramButton(label="Make it so", data="go:1"),
                                         TelegramButton(label="Skip", data="skip:1")], reply_to=5)
    body = _body(bot.requests[0])
    assert body["reply_markup"] == {"inline_keyboard": [[{"text": "Make it so", "callback_data": "go:1"},
                                                         {"text": "Skip", "callback_data": "skip:1"}]]}
    assert body["reply_parameters"] == {"message_id": 5, "allow_sending_without_reply": True}


def test_long_text_is_split_and_buttons_go_under_the_last_part(bot):
    bot.answers = [{"message_id": 1}, {"message_id": 2}]
    text = "a" * 3000 + "\n\n" + "b" * 3000
    assert tg.send_message(text, buttons=[TelegramButton(label="OK", data="ok")], reply_to=9) == 2
    first, last = (_body(r) for r in bot.requests)
    assert first["text"] == "a" * 3000 and last["text"] == "b" * 3000
    assert "reply_markup" not in first and "reply_markup" in last
    assert "reply_parameters" in first and "reply_parameters" not in last


@pytest.mark.parametrize("text", ["", "   ", None])
def test_empty_text_is_refused(bot, text):
    with pytest.raises(ValueError):
        tg.send_message(text)
    assert bot.requests == []


@pytest.mark.parametrize("button", [TelegramButton(label="X", data=""), TelegramButton(label=" ", data="x"),
                                    TelegramButton(label="X", data="x" * 65)])
def test_invalid_buttons_are_refused(bot, button):
    with pytest.raises(ValueError):
        tg.send_message("hi", buttons=[button])
    assert bot.requests == []


def test_split_text():
    assert tg.split_text("short", limit=10) == ["short"]
    assert tg.split_text("one two three four", limit=10) == ["one two", "three four"]
    assert tg.split_text("para one\n\npara two", limit=12) == ["para one", "para two"]
    assert tg.split_text("x" * 25, limit=10) == ["x" * 10, "x" * 10, "x" * 5]  # no break: cut hard
    assert all(len(p) <= tg.MAX_TEXT for p in tg.split_text("word " * 3000))


# ---------- receiving ----------
def test_get_updates_returns_the_authors_texts_and_buttons(bot):
    bot.answer = [_text_update(10, "make it so", reply_to=42), _button_update(11, "skip:abc")]
    result = tg.get_updates(offset=10, wait=30)
    body = _body(bot.requests[0])
    assert body == {"timeout": 30, "allowed_updates": ["message", "callback_query"], "offset": 10}
    assert bot.timeouts == [tg.TIMEOUT + 30]  # the HTTP timeout covers the long poll
    text, button = result.items
    assert (text.kind, text.text, text.message_id, text.reply_to_message_id) == ("text", "make it so", 110, 42)
    assert (button.kind, button.text, button.message_id, button.callback_id) == ("button", "skip:abc", 42, "cb11")
    assert result.next_offset == 12


@pytest.mark.parametrize("update", [
    _text_update(20, "make it so", chat=STRANGER, sender=STRANGER),  # someone else found the bot
    _text_update(20, "make it so", chat=AUTHOR, sender=STRANGER),  # not sent by the author
    _button_update(20, "go:1", chat=STRANGER, sender=STRANGER),
    _button_update(20, "go:1", chat=AUTHOR, sender=STRANGER),
    {"update_id": 20, "message": {"message_id": 1, "date": 1, "chat": {"id": AUTHOR}, "from": {"id": AUTHOR},
                                  "photo": []}},  # not a text
    {"update_id": 20, "edited_message": {}},  # a kind the agent does not use
])
def test_updates_not_from_the_author_are_dropped_but_confirmed(bot, update):
    bot.answer = [update]
    result = tg.get_updates()
    assert result.items == []
    assert result.next_offset == 21  # confirmed: Telegram will not send it again


def test_no_updates_keeps_the_offset(bot):
    bot.answer = []
    assert tg.get_updates(offset=5).next_offset == 5
    assert tg.get_updates().next_offset is None


def test_wait_is_capped(bot):
    bot.answer = []
    tg.get_updates(wait=999)
    assert _body(bot.requests[0])["timeout"] == tg.MAX_WAIT


# ---------- buttons ----------
def test_answer_button(bot):
    tg.answer_button("cb1", "Posted")
    assert _method(bot.requests[0]) == "answerCallbackQuery"
    assert _body(bot.requests[0]) == {"callback_query_id": "cb1", "text": "Posted"}


def test_answering_a_press_too_late_is_fine(bot):
    bot.answer = (400, {"ok": False, "error_code": 400, "description": "Bad Request: query is too old and response "
                                                                       "timeout expired or query ID is invalid"})
    tg.answer_button("cb1")  # no error


def test_other_answer_errors_still_raise(bot):
    bot.answer = (400, {"ok": False, "error_code": 400, "description": "Bad Request: something else"})
    with pytest.raises(tg.TelegramError):
        tg.answer_button("cb1")


def test_remove_buttons(bot):
    tg.remove_buttons(42)
    assert _method(bot.requests[0]) == "editMessageReplyMarkup"
    assert _body(bot.requests[0]) == {"chat_id": AUTHOR, "message_id": 42, "reply_markup": {"inline_keyboard": []}}


def test_remove_buttons_on_a_message_without_buttons_is_fine(bot):
    bot.answer = (400, {"ok": False, "error_code": 400,
                        "description": "Bad Request: message is not modified: specified new message content and "
                                       "reply markup are exactly the same"})
    tg.remove_buttons(42)  # no error


# ---------- errors ----------
@pytest.mark.parametrize("status,code,expected", [
    (401, 401, 503),  # token invalid
    (404, 404, 503),  # no bot with this token
    (403, 403, 503),  # the author blocked the bot / never pressed Start
    (429, 429, 429),
    (400, 400, 502),
    (500, 500, 502),
])
def test_bot_api_errors_map_to_statuses(bot, status, code, expected):
    bot.answer = (status, {"ok": False, "error_code": code, "description": "boom",
                           "parameters": {"retry_after": 7}})
    with pytest.raises(tg.TelegramError) as e:
        tg.send_message("hi")
    assert e.value.status_code == expected
    if expected == 429:
        assert e.value.retry_after == 7


def test_invalid_json_is_502(bot):
    bot.answer = (502, None)
    with pytest.raises(tg.TelegramError) as e:
        tg.bot_info()
    assert e.value.status_code == 502


def test_timeout_is_504(bot):
    bot.error = httpx.ReadTimeout("slow")
    with pytest.raises(tg.TelegramError) as e:
        tg.bot_info()
    assert e.value.status_code == 504


def test_connection_error_is_502_and_never_shows_the_token(bot, caplog):
    bot.error = httpx.ConnectError(f"failed for https://api.telegram.org/bot{TOKEN}/getMe")
    with pytest.raises(tg.TelegramError) as e:
        tg.bot_info()
    assert e.value.status_code == 502
    assert TOKEN not in str(e.value)
    assert TOKEN not in caplog.text
