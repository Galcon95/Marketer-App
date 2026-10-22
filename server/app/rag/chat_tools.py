"""Tools the "Ask your book" chat model may call (LangChain tool calling, one round; see qa.py).

    list_books          the client's library: ids, titles, authors, themes             (no model call)
    check_platform_fit  does a post work on X, LinkedIn, ...? (core/platforms.py)        (no model call)
    draft_social_post   write a grounded post with citations and save it as an asset    (generation graph)

Book content is NOT a tool: the chat's fixed RAG step already puts the relevant passages into the prompt,
so the tools only add what retrieval cannot do (library data, a calculation, an action). Security checks
are not tools either; they run on every question in code (api/knowledge.py, core/guard.py).

The docstrings are what the model reads to choose a tool, so they say when to use it and when not.
run_tool_calls executes the model's calls: unknown tools and invalid arguments become error results
for the model instead of exceptions, and at most MAX_TOOL_CALLS run per answer.
"""

import json
import logging
import re
import time
from functools import cache

from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool, ToolException, tool

from app.core.platforms import check_platform_fit as platform_fit
from app.core.schemas import GenerateRequest, Platform, Tone, ToolCallRecord
from app.rag import generation
from app.rag.library import book_info, find_book, known_books, ready_books

logger = logging.getLogger(__name__)

MAX_TOOL_CALLS = 3  # tool calls run per answer; further ones get an error result
MAX_RESULT_CHARS = 6000  # a tool result is cut to this length for the model


@cache
def make_tools(project_id: str) -> list[BaseTool]:
    """The chat tools for one client (project), in the order the model sees them."""

    @tool(parse_docstring=True)
    def list_books() -> list[dict]:
        """List the client's library: every processed book with its book_id, title, author, number of passages,
        whether a summary exists and its key themes. Use it for questions about the library itself (which books,
        how many, by whom, which book fits a topic or audience), not for what a book says; the source passages
        in the prompt cover book content.
        """
        return [book_info(s).model_dump() for s in ready_books(project_id)]

    @tool(parse_docstring=True)
    def check_platform_fit(text: str, platform: Platform) -> dict:
        """Check whether a social media post works on a platform: character limit, recommended words and
        hashtags, what shows before "more", and AI-sounding clichés. Use it when the user asks whether a text
        fits or works on a platform, or wants a post checked. No need to call it after draft_social_post,
        which already includes this check.

        Args:
            text: The post exactly as it would be published.
            platform: One of x, linkedin, instagram, facebook, tiktok, youtube.
        """
        return platform_fit(text, platform).model_dump()

    @tool(parse_docstring=True)
    def draft_social_post(book: str, platform: Platform, angle: str, tone: Tone = "neutral") -> dict:
        """Write a new social media post grounded in one of the client's books (with citations from the book)
        and save it in the asset library. Use it only when the user asks for a post to be written. Returns the
        post, its asset id, the number of cited passages and the platform check.

        Args:
            book: The book's title (or a distinctive part of it) or its book_id.
            platform: One of x, linkedin, instagram, facebook, tiktok, youtube.
            angle: What the post should say or achieve, in one or two sentences, e.g. "the book's rule for when to sell, as a practical tip".
            tone: One of neutral, inspiring, friendly, professional, punchy, literary.
        """
        source = find_book(project_id, book)
        if source is None:
            raise ToolException(f"No single book matches '{book}'. Known books: {known_books(project_id)}.")
        asset = generation.create_asset(project_id, GenerateRequest(
            asset_type="social_post", brief=angle, platform=platform, tone=tone, source_ids=[source.id]))
        post = re.sub(r"\s*\[\d+\]", "", asset.text).strip()
        return {"asset_id": asset.id, "post": post, "cited_passages": len(asset.citations),
                "platform_fit": platform_fit(post, platform).model_dump(), "tokens": asset.tokens}

    return [list_books, check_platform_fit, draft_social_post]


def run_tool_calls(project_id: str, tool_calls: list[dict]) -> tuple[list[ToolMessage], list[ToolCallRecord]]:
    """Run the tool calls of a model reply, in order.

    Every call gets a ToolMessage answer (the API requires one per call id): the result as JSON, or an
    error text for unknown tools, invalid arguments, failures and calls beyond MAX_TOOL_CALLS.

    Returns:
        The ToolMessages for the model and a ToolCallRecord per call for the GUI.
    """
    tools = {t.name: t for t in make_tools(project_id)}
    messages: list[ToolMessage] = []
    records: list[ToolCallRecord] = []
    for i, call in enumerate(tool_calls):
        name, args = call["name"], call.get("args") or {}
        started = time.perf_counter()
        ok, result = False, None
        if i >= MAX_TOOL_CALLS:
            result = f"Not run: at most {MAX_TOOL_CALLS} tool calls per answer."
        elif name not in tools:
            result = f"Unknown tool '{name}'."
        else:
            try:
                result, ok = tools[name].invoke(args), True
            except Exception as e:  # invalid arguments (ValidationError), ToolException, generation errors
                logger.warning("Chat tool %s failed: %s", name, e)
                result = f"Error: {e}"
        records.append(ToolCallRecord(name=name, arguments=args, ok=ok, result=result,
                                      duration_ms=round((time.perf_counter() - started) * 1000)))
        content = json.dumps(result, ensure_ascii=False, default=str) if ok else str(result)
        messages.append(ToolMessage(content=content[:MAX_RESULT_CHARS], tool_call_id=call["id"], name=name,
                                    status="success" if ok else "error"))
    return messages, records
