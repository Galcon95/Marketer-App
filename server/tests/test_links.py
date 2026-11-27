"""Links in model-written texts (core/links.py): only the author's own book links stay, everything else that would
become a link on Facebook, YouTube or Telegram is taken out, and the author is told."""

import pytest

from app.core import links
from app.core.schemas import AutomationSchedule
from app.agents import automation
from tests.conftest import OWNER

BOOK = "https://www.amazon.com/dp/B0EXAMPLE"


@pytest.mark.parametrize("text, expected, removed", [
    ("Read more at https://evil.example/x?a=1.", "Read more at.", ["https://evil.example/x?a=1"]),
    ("Get it here: www.phish.com/login", "Get it here:", ["www.phish.com/login"]),
    ("Write to me at fan@mail.com, I answer!", "Write to me at, I answer!", ["fan@mail.com"]),
    ("See bit.ly/abc for the rest.", "See for the rest.", ["bit.ly/abc"]),
    ("A link (https://x.io) in brackets.", "A link in brackets.", ["https://x.io"]),
    ("No link at all, e.g. here. Version 2.0 is fine.", "No link at all, e.g. here. Version 2.0 is fine.", []),
])
def test_foreign_links_are_removed(text, expected, removed):
    assert links.keep_own_links(text, []) == (expected, removed)


@pytest.mark.parametrize("link", [BOOK, "https://amazon.com/dp/B0EXAMPLE/", "amazon.com/dp/B0EXAMPLE",
                                  "https://www.amazon.com/dp/B0EXAMPLE?ref=fb"])
def test_the_own_book_link_stays_however_it_is_written(link):
    text = f"My book: {link}"
    assert links.keep_own_links(text, [BOOK]) == (text, [])


def test_another_page_on_the_same_site_is_not_own():
    text, removed = links.keep_own_links("Also https://www.amazon.com/dp/B0OTHER and " + BOOK, [BOOK])
    assert removed == ["https://www.amazon.com/dp/B0OTHER"] and BOOK in text


def test_own_links_are_the_users_book_links():
    automation.save(OWNER.id, AutomationSchedule(every_minutes=60, book_links={"src_1": BOOK}))
    assert links.own_links(OWNER.id) == [BOOK]
    assert links.own_links(None) == [] and links.own_links("nobody") == []


def test_the_note_for_the_author():
    assert links.note([]) == ""
    assert links.note(["evil.com"]) == "Removed a link that is not one of your book links: evil.com."
    assert "4 links that are" in links.note(["a.com", "b.com", "c.com", "d.com"]) and "1 more" in links.note(
        ["a.com", "b.com", "c.com", "d.com"])
