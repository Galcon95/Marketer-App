"""Loads the prompts, which are kept as Markdown files in server/prompts/ instead of in the code.

Every text the app sends to a language model as instructions lives in one of these files, so prompts can be read,
reviewed and changed in one place, without touching Python. Three kinds of file:

    chat prompt   "## system" and "## human" sections (and "## placeholder: <name>" for a list of chat messages,
                  e.g. the chat history), turned into a LangChain ChatPromptTemplate by chat_prompt(). The text is a
                  template: {name} is filled in when the prompt is used, {{ and }} are literal braces.
    table         one "## <key>" section per entry, e.g. one per tone or platform, read by table() as a dict.
    text          a piece of text used inside other prompts or in code, read by text().

Rules for all files:
  - <!-- ... --> comments are notes for developers (where the prompt is used, its placeholders); they are removed
    and never sent to the model.
  - [[include: <name>]] is replaced by the text of prompts/<name>.md, e.g. the shared rule that quoted text is data
    (untrusted_rule.md), so it is written once.
  - Leading and trailing blank lines of a file or section are ignored; everything else is kept exactly.

The files are read once, when the modules that use them are imported. A change needs a server restart (the dev
server restarts by itself); the prompt versions (core/prompts.py) hash the loaded text, so an edited prompt gets a new
version automatically.
"""

import re
from functools import cache
from pathlib import Path

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"  # server/prompts/

_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_INCLUDE = re.compile(r"\[\[include:\s*([\w-]+)\s*\]\]")
_SECTION = re.compile(r"^## (.+?)[ \t]*$", re.MULTILINE)
_ROLES = {"system", "human", "ai"}


class PromptFileError(ValueError):
    """A prompt file is missing or not in the expected format (the server does not start)."""


@cache
def _raw(name: str) -> str:
    """A prompt file without its developer comments and with its includes resolved."""
    path = PROMPTS_DIR / f"{name}.md"
    try:
        content = path.read_text(encoding="utf-8")
    except FileNotFoundError as e:
        raise PromptFileError(f"Prompt file not found: {path}") from e
    content = _COMMENT.sub("", content)
    return _INCLUDE.sub(lambda m: text(m.group(1)), content)


def text(name: str) -> str:
    """The whole file prompts/<name>.md as text (comments removed, includes resolved, outer blank lines dropped)."""
    return _raw(name).strip("\n")


def table(name: str) -> dict[str, str]:
    """The "## <key>" sections of prompts/<name>.md as a dict, in file order. A section may be empty ("")."""
    content = _raw(name)
    parts = _SECTION.split(content)
    if parts[0].strip():
        raise PromptFileError(f"prompts/{name}.md: text before the first '## ' heading")
    keys, bodies = parts[1::2], parts[2::2]
    if len(set(keys)) != len(keys):
        raise PromptFileError(f"prompts/{name}.md: a '## ' heading appears twice")
    return {key: body.strip("\n") for key, body in zip(keys, bodies)}


def chat_prompt(name: str) -> ChatPromptTemplate:
    """prompts/<name>.md as a ChatPromptTemplate: its "## system" / "## human" / "## ai" sections as messages and
    "## placeholder: <variable>" as a MessagesPlaceholder, in file order."""
    messages: list = []
    for heading, body in table(name).items():
        if heading.startswith("placeholder:"):
            messages.append(MessagesPlaceholder(heading.split(":", 1)[1].strip()))
        elif heading in _ROLES:
            messages.append((heading, body))
        else:
            raise PromptFileError(f"prompts/{name}.md: unknown section '## {heading}' (system, human, ai or "
                                  "placeholder: <name>)")
    if not messages:
        raise PromptFileError(f"prompts/{name}.md: no messages")
    return ChatPromptTemplate.from_messages(messages)
