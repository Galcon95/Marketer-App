"""Links in model-written texts: only the author's own book links stay (keep_own_links).

A model can be talked into adding a link by a text it reads: a planted line in a book, in a reader's comment or in a
web page ("add this link to your answer"). A link is how such an injection would send readers, or data, somewhere
else. So every text a model writes for posting (agents' replies, comments and book posts; Content Studio posts,
campaign posts and discussion replies) loses every link and e-mail address that is not one of the author's book links
(Agent Workspace → "Where to get it", AutomationSchedule.book_links). The author's own text (Telegram "Edit", edits
in the app) is never changed: the author may add any link they like.

    own_links(user_id)            the user's book links
    keep_own_links(text, own)     the text without other links, and the links removed
"""

import logging
import re

logger = logging.getLogger(__name__)

# A link: with a scheme, starting with www., an e-mail address, or a bare domain with a common ending (Facebook,
# YouTube and Telegram turn "example.com/x" into a link too).
_TLDS = ("com|net|org|io|co|de|uk|eu|info|biz|xyz|ly|me|app|ai|link|site|online|shop|store|ru|cn|top|click|tk|gg|"
         "to|tv|lt|fr|it|es|nl|us|ca|au|in|page|dev|club|live|news|blog")
LINK = re.compile(r"\b(?:https?://|www\.)[^\s<>()\"'\]\[]+"
                  r"|\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b"
                  rf"|\b(?:[a-z0-9-]+\.)+(?:{_TLDS})\b(?:/[^\s<>()\"'\]\[]*)?", re.IGNORECASE)
_TRAILING = ".,;:!?"


def own_links(user_id: str | None) -> list[str]:
    """The user's book links (their Agent Workspace settings); [] without a user or settings, or if the database
    cannot be read (then every link is removed: the safe side)."""
    if not user_id:
        return []
    from app.agents import automation  # here: automation is an agent module, this one is core
    try:
        return [url for url in automation.schedule_of(user_id).book_links.values() if url]
    except OSError as e:  # DatabaseError
        logger.warning("The book links of %s cannot be read, every link is removed: %s", user_id, e)
        return []


def keep_own_links(text: str, own: list[str]) -> tuple[str, list[str]]:
    """The text without every link and e-mail address that is not one of `own` (or a page under one of them).

    Returns:
        The cleaned text, and the links that were removed (as they were written; [] when nothing changed).
    """
    allowed = [_norm(url) for url in own if url]
    removed: list[str] = []

    def drop(match: re.Match) -> str:
        link = match.group(0).rstrip(_TRAILING)
        rest = match.group(0)[len(link):]  # punctuation after the link stays
        key = _norm(link)
        if any(key == a or (key.startswith(a) and key[len(a)] in "/?#") for a in allowed):
            return match.group(0)
        removed.append(link)
        return rest

    cleaned = LINK.sub(drop, text)
    if not removed:
        return text, []
    cleaned = re.sub(r"\(\s*\)|\[\s*\]", "", cleaned)  # brackets that held only the link
    cleaned = re.sub(r"[ \t]+([.,;:!?])", r"\1", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = "\n".join(line.rstrip() for line in cleaned.splitlines())
    logger.info("Removed %d link(s) that are not the author's own: %s", len(removed), ", ".join(removed[:5]))
    return cleaned.strip(), removed


def note(removed: list[str]) -> str:
    """One line for the author about removed links ("" when none were)."""
    if not removed:
        return ""
    shown = ", ".join(removed[:3]) + (f" and {len(removed) - 3} more" if len(removed) > 3 else "")
    return (f"Removed {'a link' if len(removed) == 1 else f'{len(removed)} links'} that "
            f"{'is' if len(removed) == 1 else 'are'} not one of your book links: {shown}.")


def _norm(url: str) -> str:
    """A link to compare: lower case, without scheme, "www." and a trailing slash."""
    url = re.sub(r"^https?://", "", url.strip().lower())
    return url.removeprefix("www.").rstrip("/")
