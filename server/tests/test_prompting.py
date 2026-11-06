"""Prompt-engineering choices: temperature per task, worked examples with a section check for the complex formats,
and the style guidance. Model calls are replaced by fakes."""

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from app.core import style
from app.core.llm import TEMPERATURES
from app.core.schemas import GenerateRequest
from app.rag import generation, qa, summary


# ---------- temperature per task ----------
def test_factual_steps_are_deterministic_and_answers_nearly():
    for task in ("condense", "filters", "plan_query", "chapter_summary", "book_overview"):
        assert TEMPERATURES[task] == 0.0
    assert 0.0 < TEMPERATURES["answer"] <= 0.3


def test_summaries_are_written_at_their_task_temperature(monkeypatch):
    seen = []

    def fake_structured(prompt, values, schema, what, temperature=0.7):
        seen.append(temperature)
        return summary.ChapterDigest(is_content=True, summary="A summary."), 1

    monkeypatch.setattr(summary, "structured", fake_structured)
    summary._summarize_chapter({"index": 0, "book": "B", "chapter": "I.", "first_page": 1, "last_page": 2, "text": "t"})
    assert seen == [TEMPERATURES["chapter_summary"]]


def test_chat_answers_use_the_answer_temperature(monkeypatch):
    seen = []

    class Fake:
        def bind_tools(self, tools, tool_choice=None):
            return RunnableLambda(lambda _: AIMessage("", tool_calls=[
                {"name": "QAAnswer", "args": {"answer": "Yes [1].", "used_sources": [1]}, "id": "c1"}]))

    def fake_chat_model(temperature=0.7):
        seen.append(temperature)
        return Fake()

    monkeypatch.setattr(qa, "chat_model", fake_chat_model)
    qa._invoke_answer([], None)
    assert seen == [TEMPERATURES["answer"]]


# ---------- worked examples and the section check ----------
@pytest.mark.parametrize("asset_type", ["video_script", "youtube_video"])
def test_the_examples_have_every_required_section(asset_type):
    assert generation.missing_sections(asset_type, generation.FORMAT_EXAMPLES[asset_type]) == []


def test_missing_headings_are_found_and_markdown_is_tolerated():
    script = generation.FORMAT_EXAMPLES["video_script"]
    without_cta = "\n".join(line for line in script.splitlines() if not line.startswith("CTA"))
    assert generation.missing_sections("video_script", without_cta) == ["CTA"]
    assert generation.missing_sections("video_script", script.replace("HOOK:", "**HOOK:**")) == []
    assert generation.missing_sections("blurb", "Any text.") == []


def test_examples_go_into_the_instructions_of_their_format_only():
    video = generation.build_instructions(GenerateRequest(asset_type="video_script", platform="tiktok", brief="A teaser."))
    assert "<example>" in video and "SCENE 1" in video
    assert "<example>" not in generation.build_instructions(GenerateRequest(asset_type="blurb", brief="A blurb."))


def test_a_draft_without_its_headings_is_written_once_more():
    state = {"req": GenerateRequest(asset_type="youtube_video", humanize=0, brief="A review."), "draft": "Title options:\n1. A\n\nTags:\nx",
             "context": []}
    first = {**state, **generation._check_style(state)}
    assert first["missing_sections"] == ["Description:", "Chapters:"]
    assert generation._after_check(first) == "generate"
    second = {**first, **generation._check_style(first)}
    assert generation._after_check(second) == "finalize"  # at most one extra draft


def test_the_second_draft_is_told_what_was_missing(monkeypatch):
    seen = []

    def fake_model(prompt_value):
        seen.append(prompt_value.to_messages()[-1].content)
        return AIMessage("HOOK: ...")

    monkeypatch.setattr(generation, "chat_model", lambda temperature=0.7: RunnableLambda(fake_model))
    req = GenerateRequest(asset_type="video_script", grounded=False, brief="A short teaser.")
    generation._generate({"req": req, "missing_sections": ["CTA", "CAPTION"]})
    assert "lacked these required section headings: CTA, CAPTION" in seen[0]


# ---------- banned phrases: kept in the prompt, because measured to help ----------
def test_style_levels_describe_the_voice_without_quoting_patterns():
    for _, text in style.HUMAN_LEVELS:
        assert not [t for t in style.AI_TELLS if t in text.lower()]


def test_the_cliche_list_is_in_the_prompt_from_level_50_on():
    assert "dive into" not in style.style_guidance(25)
    assert "dive into" in style.style_guidance(50)


def test_ai_tells_are_still_found_after_generation():
    assert "dive into" in style.find_ai_tells("Let's dive into this book.")
