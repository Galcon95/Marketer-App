"""Scan Reddit or Substack for discussions (Community): find recent Reddit threads, or Substack posts and Notes, on a
topic and rank them by how well one book could add to them, so the author can pick some for the Discussion Relevance
Agent (agents/discussion.py).

    search (Tavily, one search per subreddit / publication, or one for the whole site) ─► keep threads, clean ─►
    triage (one model call)

This is a fixed pipeline, not an agent: the steps and their order are set in code. The agent's decision about a single
discussion (contribute / more_context / skip, with a reply) comes later, when the author picks a thread.

Why Tavily: Reddit closed its public JSON to servers (HTTP 403) and no longer approves new Data API apps (2026), so the
app finds threads through Tavily's web search (langchain-tavily, TAVILY_API_KEY) restricted to reddit.com. Tavily gives
title, URL and a snippet; for some threads also the page text with the post and top comments ("full_text"). It gives
no votes, comment counts or dates, and cannot fetch a thread on demand (Reddit blocks that too), so for threads
without full text the author opens the thread and copies the discussion.

Why Tavily for Substack too: Substack has no public API (neither for reading nor for posting). Tavily finds posts on
<publication>.substack.com (and Notes, when indexed) with their article text; the comments are not in it (they load
later on the page), so the agent answers the post itself. Publications on their own domain are not found.

Everything Tavily returns is third-party text: cleaned by the guard and given to the model only as quoted <post>
blocks under guard.UNTRUSTED_RULE; each thread is also scanned for prompt injection (guard.scan_third_party) and
flagged in the result, so the author sees the risk before picking it. Nothing is saved. The triage prompt is
prompts/discussion_scan_triage.md. Runs are traced in LangSmith as "scan_discussions".
"""

import logging
import re
from typing import Any

from langchain_tavily import TavilySearch
from pydantic import BaseModel, Field

from app.core import prompt_files
from app.agents.discussion_tools import BookNotReady, ready_books
from app.core import config, prompts, tracing
from app.core import state as db
from app.core.guard import clean_text, quote_untrusted, scan_third_party
from app.core.llm import TEMPERATURES, GenerationError, is_configured, model_failure, structured
from app.core.schemas import Fit, ScannedThread, ScanRequest, ScanResult, ScanSite
from app.rag.retrieval import source_name

logger = logging.getLogger(__name__)

MAX_TRIAGE = 30  # threads the model ranks at most (the best by search score when more were found)
MAX_FULL_TEXT = 7000  # characters of a thread's page text kept (the agent's discussion limit is 8000, with the title)
EXCERPT_CHARS = 600  # characters of each thread the triage sees
HEADER_LINES = 20  # lines at the top of a page searched for the title (where the post begins)
FIT_ORDER: dict[Fit, int] = {"high": 0, "medium": 1, "low": 2}
SITE_NAMES: dict[ScanSite, str] = {"reddit": "Reddit", "substack": "Substack"}
# What the triage prompt calls the items of each site ({items}).
SITE_ITEMS: dict[ScanSite, str] = {"reddit": "Reddit threads", "substack": "Substack posts and Notes"}

TRIAGE_PROMPT = prompt_files.chat_prompt("discussion_scan_triage")  # prompts/discussion_scan_triage.md


class ThreadFit(BaseModel):
    """How well the book fits one thread."""

    n: int = Field(description="The thread's number, as in <post n=\"...\">.")
    fit: Fit = Field(description="'high', 'medium' or 'low', as defined in the instructions.")
    why: str = Field(min_length=1, description="One sentence for the author: how the book connects to the thread, or "
                                               "why it does not.")


class Triage(BaseModel):
    """Your rating of every thread."""

    threads: list[ThreadFit] = Field(description="One rating per thread, for every thread.")


# Version of this feature's prompt, schema and settings (core/prompts.py).
PROMPT_VERSION = prompts.register("discussion_scan", TRIAGE_PROMPT, Triage, {
    "temperature": TEMPERATURES["triage"], "max_triage": MAX_TRIAGE, "excerpt_chars": EXCERPT_CHARS,
    "site_items": SITE_ITEMS})


# ---------- Public API ----------
def scan_discussions(project_id: str, req: ScanRequest) -> ScanResult:
    """Search Reddit (threads) or Substack (posts and Notes) on the topic and rank them for one book. Nothing is saved.

    Args:
        project_id: The client whose book to use.
        req: The book, the topic (already checked by the guard), the site, optional subreddits or publications, time
            range and result count.

    Returns:
        The threads, best fit first (high, medium, low; within a fit by search score).

    Raises:
        BookNotReady: If the book is not a processed book of this client.
        GenerationError: 503 if no Tavily or model key is configured; 502 if the search or the model call fails;
            504 on a timeout.
    """
    if not any(s.id == req.source_id for s in ready_books(project_id)):
        raise BookNotReady(f"Book {req.source_id} is not a processed book of this client.")
    if not config.TAVILY_API_KEY:
        raise GenerationError(503, "No Tavily key set. Add TAVILY_API_KEY to server/.env and restart the server.")
    if not is_configured():
        raise GenerationError(503, "No API key set. Add OPENROUTER_API_KEY (or OPENAI_API_KEY) and restart the server.")
    with tracing.scope():
        if req.site == "substack":
            threads = search_substack(req.topic, req.publications, req.time_range, req.max_results)
        else:
            threads = search_reddit(req.topic, req.subreddits, req.time_range, req.max_results)
        if req.site == "substack" and (own := getattr(db.projects.get(project_id), "substack", "")):
            threads = [t for t in threads if t["community"] != own]  # the author's own posts are no discussions to join
        found = len(threads)
        threads = sorted(threads, key=lambda t: -t["score"])[:MAX_TRIAGE]
        rated, tokens = _triage(req, threads) if threads else ([], 0)
    rated.sort(key=lambda t: (FIT_ORDER[t.fit], -t.score))
    return ScanResult(source_id=req.source_id, topic=req.topic, site=req.site, subreddits=req.subreddits,
                      publications=req.publications, time_range=req.time_range, threads=rated, found=found,
                      tokens=tokens, model=config.LLM_MODEL, prompt_version=PROMPT_VERSION)


def search_reddit(topic: str, subreddits: list[str], time_range: str, max_results: int) -> list[dict[str, Any]]:
    """Find Reddit threads on the topic with Tavily: one search per subreddit, or one over all of Reddit.

    Returns:
        One dict per thread (url, subreddit, title, snippet, full_text, score), without duplicates; subreddit pages,
        user pages and the like are left out.

    Raises:
        GenerationError: 502 if a search fails.
    """
    domains = [[f"reddit.com/r/{s}"] for s in subreddits] or [["reddit.com"]]
    return _collect(topic, domains, time_range, max_results, _thread, "reddit")


def search_substack(topic: str, publications: list[str], time_range: str, max_results: int) -> list[dict[str, Any]]:
    """Find Substack posts and Notes on the topic with Tavily: one search per publication, or one over all of
    Substack.

    Returns:
        One dict per post or Note (url, community, title, snippet, full_text, score), without duplicates; front pages,
        archives, profiles and the like are left out.

    Raises:
        GenerationError: 502 if a search fails.
    """
    domains = [[f"{p}.substack.com"] for p in publications] or [["substack.com"]]
    return _collect(topic, domains, time_range, max_results, _substack_item, "substack")


def _collect(topic: str, domains: list[list[str]], time_range: str, max_results: int,
             to_thread: Any, site: ScanSite) -> list[dict[str, Any]]:
    """One Tavily search per domain list; the hits that `to_thread` accepts, each once."""
    tool = TavilySearch(max_results=max_results, time_range=time_range, include_raw_content="text",
                        tavily_api_key=config.TAVILY_API_KEY)
    threads: dict[str, dict[str, Any]] = {}
    for include in domains:
        for hit in _search(tool, topic, include, site):
            if (thread := to_thread(hit)) and thread["id"] not in threads:
                threads[thread["id"]] = thread
    return list(threads.values())


# ---------- Steps ----------
def _search(tool: TavilySearch, query: str, include_domains: list[str], site: ScanSite = "reddit") -> list[dict[str, Any]]:
    """One Tavily search; no results is an empty list, any other failure a 502."""
    failed = f"The {SITE_NAMES[site]} search failed (Tavily). Please try again in a moment."
    try:
        result = tool.invoke({"query": query, "include_domains": include_domains})
    except Exception as e:
        if "no search results" in str(e).lower():
            return []
        logger.warning("Tavily search failed for %s: %s", include_domains, e)
        raise GenerationError(502, failed) from e
    if isinstance(result, str) and "no search results" in result.lower():  # how the tool reports an empty search
        return []
    if not isinstance(result, dict):  # the tool reports some errors as text
        logger.warning("Tavily search returned no results object: %.200s", result)
        raise GenerationError(502, failed)
    return result.get("results") or []


_THREAD_URL = re.compile(r"^https?://(?:www\.|old\.|new\.)?reddit\.com/r/([A-Za-z0-9_]+)/comments/([a-z0-9]+)", re.I)
_TITLE_SUFFIX = re.compile(r"\s*:\s*r/[A-Za-z0-9_]+\s*$")


def _thread(hit: dict[str, Any]) -> dict[str, Any] | None:
    """A Tavily result as a thread, or None when it is not a Reddit thread (e.g. a subreddit's front page)."""
    match = _THREAD_URL.match(hit.get("url") or "")
    if not match:
        return None
    subreddit, post_id = match.groups()
    title = clean_text(_TITLE_SUFFIX.sub("", hit.get("title") or "")).strip() or "(untitled thread)"
    return {"id": post_id.lower(), "url": hit["url"].split("?")[0], "site": "reddit", "community": subreddit,
            "title": title, "snippet": clean_text(hit.get("content") or "").strip(),
            "full_text": clean_page(hit.get("raw_content") or "", title),
            "score": float(hit.get("score") or 0.0)}


# Substack: a post on <publication>.substack.com/p/<slug> (or open.substack.com/pub/<publication>/p/<slug>), a Note
# on substack.com/@<author>/note/c-<id>, or a post shown in the app at substack.com/home/post/p-<id> or
# substack.com/@<author>/p-<id>.
_SUBSTACK_POST = re.compile(r"^https?://([a-z0-9][a-z0-9-]*)\.substack\.com/p/([a-z0-9][a-z0-9-]*)", re.I)
_SUBSTACK_OPEN_POST = re.compile(r"^https?://open\.substack\.com/pub/([a-z0-9][a-z0-9-]*)/p/([a-z0-9][a-z0-9-]*)",
                                 re.I)
_SUBSTACK_NOTE = re.compile(r"^https?://(?:www\.)?substack\.com/@([A-Za-z0-9_.-]+)/note/(c-\d+)", re.I)
_SUBSTACK_APP_POST = re.compile(r"^https?://(?:www\.)?substack\.com/(?:home/post|@([A-Za-z0-9_.-]+))/(p-\d+)", re.I)


def _substack_item(hit: dict[str, Any]) -> dict[str, Any] | None:
    """A Tavily result as a Substack post or Note, or None for anything else (a front page, archive, profile, ...)."""
    url = (hit.get("url") or "").split("?")[0].split("#")[0]
    if (match := _SUBSTACK_POST.match(url)) and match.group(1).lower() not in ("www", "open"):
        community, item_id = match.group(1).lower(), f"{match.group(1)}/{match.group(2)}".lower()
        url = f"https://{community}.substack.com/p/{match.group(2)}"
    elif match := _SUBSTACK_OPEN_POST.match(url):
        community, item_id = match.group(1).lower(), f"{match.group(1)}/{match.group(2)}".lower()
        url = f"https://{community}.substack.com/p/{match.group(2)}"
    elif match := _SUBSTACK_NOTE.match(url):
        community, item_id, url = f"@{match.group(1)}", match.group(2).lower(), match.group(0)
    elif match := _SUBSTACK_APP_POST.match(url):
        community, item_id, url = f"@{match.group(1)}" if match.group(1) else "", match.group(2).lower(), match.group(0)
    else:
        return None
    title = clean_text(hit.get("title") or "").strip() or "(untitled post)"
    return {"id": item_id, "url": url, "site": "substack", "community": community, "title": title,
            "snippet": clean_text(hit.get("content") or "").strip(),
            "full_text": clean_page(hit.get("raw_content") or "", title, "substack"),
            "score": float(hit.get("score") or 0.0)}


def _triage(req: ScanRequest, threads: list[dict[str, Any]]) -> tuple[list[ScannedThread], int]:
    """Rate every thread for the book in one structured model call. A thread the model skips counts as low."""
    blocks = "\n\n".join(
        quote_untrusted(f"Title: {t['title']}\n{_excerpt(t)}", "post", n=i,
                        **({"subreddit": t["community"]} if req.site == "reddit" else {"where": t["community"]}))
        for i, t in enumerate(threads, 1))
    try:
        triage, tokens = structured(TRIAGE_PROMPT, {"book": _book(req.source_id), "topic": req.topic,
                                                    "items": SITE_ITEMS[req.site], "threads": blocks},
                                    Triage, "thread ranking", TEMPERATURES["triage"])
    except GenerationError:
        raise
    except Exception as e:
        logger.exception("Thread ranking failed")
        raise model_failure(e) from e
    fits = {f.n: f for f in triage.threads if 1 <= f.n <= len(threads)}
    rated = []
    for i, t in enumerate(threads, 1):
        f = fits.get(i)
        # Flagged for the author, not removed: the thread only reaches the agent after the author picks it (and the
        # agent scans it again). Title, page text and snippet are all scanned.
        risk, findings = scan_third_party("\n".join((t["title"], t["full_text"], t["snippet"])))
        rated.append(ScannedThread(
            url=t["url"], site=t["site"], community=t["community"],
            subreddit=t["community"] if t["site"] == "reddit" else "", title=t["title"], snippet=t["snippet"],
            full_text=t["full_text"],
            score=t["score"], fit=f.fit if f else "low", why=f.why if f else "Not rated.", injection_risk=risk,
            injection_findings=findings))
    return rated, tokens


# ---------- Helpers ----------
def _excerpt(thread: dict[str, Any]) -> str:
    """What the triage sees of a thread: the start of its page text when there is one, else the search snippet."""
    text = thread["full_text"] or thread["snippet"] or "(no text, only the title)"
    return text[:EXCERPT_CHARS] + ("…" if len(text) > EXCERPT_CHARS else "")


def _book(source_id: str) -> str:
    """The book for the prompt: "Title — Author", and its overview when a summary exists."""
    name = source_name(source_id) or source_id
    summary = db.summaries.get(source_id)
    return name + (f"\nWhat the book is about:\n{quote_untrusted(summary.summary, 'background')}" if summary else "")


# Lines of a Reddit page that are navigation, buttons or badges, not discussion.
_NOISE = re.compile(
    r"^(skip to main content|open menu.*|go to .*|sign ?up.*|log ?in.*|expand user menu.*|open settings menu|"
    r"image \d+.*|.*profile badge.*|top 1% (poster|commenter)|reply|share|reply\s+share|sort by:?.*|"
    r"open comment sort options|best|top|new|controversial|old|q&a|comments section|view in app|"
    r"sorry, something went wrong.*|\d+ more repl(y|ies)|more replies|promoted|join|read more|"
    r"archived post\..*|\W?\d+\s*(s|m|h|d|w|mo|y|yr)\.? ago|edited \d+.*|level \d+|"
    r"r/[A-Za-z0-9_]+\W*\d*\s*(s|m|h|d|w|mo|y|yr)?\.?\s*(ago)?)$",
    re.IGNORECASE)


# Lines of a Substack page that are buttons, sign-up boxes or counters, not the post.
_SUBSTACK_NOISE = re.compile(
    r"^(subscribe|subscribed|sign in|sign up|share|share this post|copy link|facebook|email|notes|more|like|comment|"
    r"restack|reply|listen|\d+|\d+ (likes?|comments?|restacks?)|type your email.*|already a paid subscriber\?.*|"
    r"continue reading.*|this post is for paid subscribers.*|upgrade to paid|discover more from .*|"
    r"thanks for reading .*|previous|next|top|latest|discussions|appreciate|"
    r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]* \d{1,2}(, \d{4})?)$",
    re.IGNORECASE)
# The first line of what follows a Substack post: comments, "Ready for more?", the footer. Everything from it is cut.
_SUBSTACK_END = re.compile(
    r"^(discussion about this post|ready for more\?|no posts|© \d{4} .*|start your substack.*|"
    r"substack is the home for .*)$", re.IGNORECASE)


def clean_page(raw: str, title: str, site: ScanSite = "reddit") -> str:
    """The discussion from a page's text: from the title on, without navigation, buttons, badges and repeated lines
    (on Substack also without everything after the post), shortened to MAX_FULL_TEXT characters. "" when there is no
    page text."""
    text = clean_text(raw)
    if not text.strip():
        return ""
    lines = [line.strip() for line in text.splitlines()]
    noise = _NOISE
    if site == "substack":
        noise = _SUBSTACK_NOISE
        end = next((i for i, line in enumerate(lines) if _SUBSTACK_END.match(line)), len(lines))
        lines = lines[:end]
    # The post starts after the title's last appearance in the page header (the first is often glued to navigation).
    key = title.lower().rstrip(". …")[:40]
    start = max((i for i, line in enumerate(lines[:HEADER_LINES]) if key and key in line.lower()), default=None)
    kept: list[str] = []
    for line in lines[start + 1 if start is not None else 0:]:
        if not line or noise.match(line) or (kept and kept[-1] == line):
            continue
        kept.append(line)
    body = "\n".join(kept).strip()
    return body[:MAX_FULL_TEXT].rstrip() + ("\n…" if len(body) > MAX_FULL_TEXT else "")
