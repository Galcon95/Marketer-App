"""Prompt versions: every model-backed feature gets a version derived from the text of the prompts it uses.

    register("qa", QA_PROMPT, TOOLS_NOTE, CONDENSE_PROMPT, FILTER_PROMPT)  →  "qa@3f9a1c2e"

The part after "@" is a short hash of the templates (system and user messages, placeholders, instruction tables,
and the structured-output schemas, whose field descriptions the model reads as instructions too),
so any edit to a prompt gives a new version by itself; nothing has to be bumped by hand, so it cannot be forgotten.
Each module registers its version next to its prompts. The version is
  - put into the graph run's metadata (LangSmith), next to the model and the request id,
  - stored with what the prompts produced: Asset, BookSummary, AskResponse (older saved data has none), and
  - recorded by the RAGAs evaluation (eval/run_eval.py) with the git commit, so score changes can be tied to
    prompt changes.
Text filled in at run time from the user or the books (passages, the question, the brief) is not part of the hash.
The chat tools' descriptions (rag/chat_tools.py) are not part of the "qa" version yet.
"""

import hashlib
import json
from typing import Any

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel

PROMPT_VERSIONS: dict[str, str] = {}  # feature name → its current version, e.g. {"qa": "qa@3f9a1c2e", ...}


def fingerprint(*parts: Any) -> str:
    """Short hash (8 hex characters) of prompt parts: chat prompt templates, strings, structured-output models
    (their JSON schema), or dicts/lists of strings."""
    digest = hashlib.sha256()
    for part in parts:
        digest.update(_text(part).encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()[:8]


def register(name: str, *parts: Any) -> str:
    """Register a feature's prompts and return its version "<name>@<hash>" (also kept in PROMPT_VERSIONS).

    Args:
        name: Feature name, e.g. "qa", "generation", "summary", "campaign".
        *parts: Every prompt the feature uses (templates, system texts, instruction tables).
    """
    version = f"{name}@{fingerprint(*parts)}"
    PROMPT_VERSIONS[name] = version
    return version


def _text(part: Any) -> str:
    """The text of a prompt part, the same on every run: messages with their role, schemas and dicts in key order."""
    if isinstance(part, ChatPromptTemplate):
        lines = []
        for message in part.messages:
            template = getattr(getattr(message, "prompt", None), "template", None)
            lines.append(f"{type(message).__name__}: "
                         + (template if template is not None else f"{{{getattr(message, 'variable_name', '')}}}"))
        return "\n".join(lines)
    if isinstance(part, str):
        return part
    if isinstance(part, type) and issubclass(part, BaseModel):
        part = part.model_json_schema()
    return json.dumps(part, sort_keys=True, ensure_ascii=False, default=str)
