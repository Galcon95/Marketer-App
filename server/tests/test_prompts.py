"""Prompt versions (core/prompts.py): derived from the prompt text, so any edit changes them; recorded on what
the prompts produce and in the run metadata. No model calls."""

import re
from datetime import datetime, timezone

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from pydantic import BaseModel, Field

from app.campaign import kit
from app.core import prompts
from app.core import state as db
from app.core.schemas import BookSummary
from app.rag import generation, qa, summary


def _prompt(system: str) -> ChatPromptTemplate:
    return ChatPromptTemplate.from_messages([("system", system), MessagesPlaceholder("history"), ("human", "{q}")])


def test_same_prompts_give_the_same_version():
    assert prompts.fingerprint(_prompt("Be brief."), {"a": "x"}) == prompts.fingerprint(_prompt("Be brief."), {"a": "x"})


def test_any_edit_gives_a_new_version():
    base = prompts.fingerprint(_prompt("Be brief."))
    assert prompts.fingerprint(_prompt("Be brief!")) != base
    assert prompts.fingerprint(ChatPromptTemplate.from_messages([("human", "Be brief.")])) != \
        prompts.fingerprint(ChatPromptTemplate.from_messages([("system", "Be brief.")]))  # the role counts too


def test_structured_output_descriptions_are_part_of_the_version():
    class Old(BaseModel):
        summary: str = Field(description="Two paragraphs.")

    class New(BaseModel):
        summary: str = Field(description="Three paragraphs.")

    assert prompts.fingerprint(Old) != prompts.fingerprint(New)


def test_every_feature_registers_a_version():
    for module, name in [(qa, "qa"), (generation, "generation"), (summary, "summary"), (kit, "campaign")]:
        assert re.fullmatch(rf"{name}@[0-9a-f]{{8}}", module.PROMPT_VERSION)
        assert prompts.PROMPT_VERSIONS[name] == module.PROMPT_VERSION


def test_answers_carry_the_prompt_version_in_response_and_metadata(monkeypatch):
    seen = {}

    class FakeGraph:
        def invoke(self, inputs, config):
            seen.update(config["metadata"])
            return {"search_query": inputs["question"], "answer": "An answer.", "citations": [], "context": [],
                    "tokens": 0}

    monkeypatch.setattr(qa, "is_configured", lambda: True)
    monkeypatch.setattr(qa, "_graph", lambda: FakeGraph())
    response = qa.answer_question("demo-campaign", "What is a bucket shop?", k=5)
    assert response.prompt_version == qa.PROMPT_VERSION
    assert seen["prompt_version"] == qa.PROMPT_VERSION


def test_summaries_from_other_prompts_are_found_for_regeneration(monkeypatch):
    def made_with(version):
        return BookSummary(source_id=f"src_{version}", summary="", themes=[], chapters=[], model="m", tokens=0,
                           created_at=datetime.now(timezone.utc), prompt_version=version)

    current, old, unversioned = made_with(summary.PROMPT_VERSION), made_with("summary@00000000"), made_with(None)
    monkeypatch.setattr(db, "summaries", {s.source_id: s for s in (current, old, unversioned)})
    assert {s.source_id for s in summary.outdated_summaries()} == {old.source_id, unversioned.source_id}
