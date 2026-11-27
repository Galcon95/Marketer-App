"""Ask the app: answers questions about using the Marketer App from the user manual (core/manual.py).

    question (+ screen, + last turns) ─► one model call with the WHOLE manual in the prompt ─► check the links ─► answer

Why the whole manual and not a search over it (RAG): the manual is small (about 4,000 words, ~6,000 tokens), so it
fits easily into one prompt. The model then sees every section at once and can combine them ("how do I get my book
into a Facebook post?" needs upload, Content Studio and Facebook), with no retrieval step that could miss the right
part. A search would only pay off for a manual many times larger, or to save tokens on very many questions.

Rules (prompts/help_answer.md): answer only from the manual, say so when it does not cover the question, explain but
never act (the assistant has no tools), answer in the language of the question. The answer is Markdown; links are
checked after the call: a link to a section that does not exist, or to anything but the manual, becomes plain text,
and any web address in the text is removed (core/links.py). Calls are recorded as "ask_app" (usage log, LangSmith).
"""

import re

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.runnables import RunnableLambda

from app.core import links, manual, prompt_files, prompts, tracing
from app.core.llm import TEMPERATURES, structured
from app.core.logs import current_request_id
from app.core.schemas import AppPage, HelpAnswer, HelpResponse, HelpSection, HelpTurn

PROMPT = prompt_files.chat_prompt("help_answer")  # prompts/help_answer.md
TEMPERATURE = TEMPERATURES["answer"]  # nearly deterministic, like Ask your book: never guess
HISTORY_TURNS = 3  # earlier turns given to the model
HISTORY_ANSWER_CHARS = 1500  # of each earlier answer

PROMPT_VERSION = prompts.register("ask_app", PROMPT, HelpAnswer, {"temperature": TEMPERATURE})

# What each screen is called in the manual, for questions like "what is this page for?".
PAGES: dict[AppPage, str] = {
    "p1": "Knowledge Hub tab (your books, summaries, Ask your book)",
    "p2": "Content Studio tab (single texts, ad pictures, campaign kits)",
    "p3": "Community tab (Reddit and Substack scans, the discussion agent, Facebook and YouTube comments)",
    "p4": "Agent Workspace tab (the marketing agent's schedule and settings)",
    "mcp": "MCP servers page (sidebar, Integrations)",
    "facebook": "Facebook Page page (sidebar, Integrations)",
    "youtube": "YouTube channel page (sidebar, Integrations)",
    "help": "the Help page (the manual)",
    "unknown": "unknown",
}

_MD_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")


def ask_app(question: str, page: AppPage = "unknown", history: list[HelpTurn] | None = None) -> HelpResponse:
    """Answer a question about using the app from the manual.

    Raises:
        OSError: If the manual cannot be read.
        GenerationError: If the model call fails (502/503/504).
    """
    text = manual.for_model()
    sections = manual.sections(text)
    titles = {a: title for _, title, a in sections}
    known = set(titles)
    values = {
        "manual": text,
        "sections": "\n".join(f"{'  ' if level == 3 else ''}- {title}: /help#{a}" for level, title, a in sections),
        "page": PAGES[page], "question": question, "history": _history_messages(history or []),
    }
    config = {"run_name": "ask_app", "tags": ["help"],
              "metadata": {"operation": "ask_app", "prompt_version": PROMPT_VERSION, "page": page,
                           "request_id": current_request_id()}}
    with tracing.scope():
        result, tokens = RunnableLambda(
            lambda v: structured(PROMPT, v, HelpAnswer, "answer about the app", TEMPERATURE)).invoke(values, config)
    used = dict.fromkeys(a for a in (_anchor_of(s) for s in result.sections) if a in known)  # in order, once
    return HelpResponse(answer=clean_answer(result.answer, known), covered=result.covered,
                        sections=[HelpSection(title=titles[a], anchor=a) for a in used], tokens=tokens)


def clean_answer(answer: str, known: set[str]) -> str:
    """The answer with only links to existing sections of the manual: any other Markdown link becomes its text,
    and any web or e-mail address left is removed (core/links.py, with no own links)."""
    def keep(match: re.Match) -> str:
        label, href = match.group(1), match.group(2)
        return match.group(0) if href in ("/help", "/help#") or _anchor_of(href) in known else label

    linked = _MD_LINK.sub(keep, answer.strip())
    cleaned, _ = links.keep_own_links(linked, [])
    return cleaned


def _anchor_of(href: str) -> str:
    """The section anchor of a manual link ("/help#books" or "#books" → "books"); "" for anything else."""
    found = re.fullmatch(r"(?:/help)?#([a-z0-9-]+)", href.strip())
    return found.group(1) if found else ""


def _history_messages(history: list[HelpTurn]) -> list[BaseMessage]:
    """The last turns as chat messages, earlier answers shortened."""
    messages: list[BaseMessage] = []
    for turn in history[-HISTORY_TURNS:]:
        messages += [HumanMessage(turn.question), AIMessage(turn.answer[:HISTORY_ANSWER_CHARS])]
    return messages
