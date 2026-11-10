"""The prompts kept as Markdown files in server/prompts/ (core/prompt_files.py): the loader's format rules, and that the
files the app uses are complete (every tone, platform and asset type has its text; no comment or include is left)."""

from typing import get_args

import pytest

from app.core import prompt_files, style
from app.core.prompt_files import PromptFileError
from app.core.schemas import AssetType, DiscussionPlatform, Platform, Tone
from app.rag import generation


@pytest.fixture
def prompts_dir(tmp_path, monkeypatch):
    """An empty prompts folder; the loader's cache is cleared before and after."""
    monkeypatch.setattr(prompt_files, "PROMPTS_DIR", tmp_path)
    prompt_files._raw.cache_clear()
    yield tmp_path
    prompt_files._raw.cache_clear()


def _write(folder, name, content):
    (folder / f"{name}.md").write_text(content, encoding="utf-8")


# ---------- the loader ----------
def test_comments_are_removed_and_includes_resolved(prompts_dir):
    _write(prompts_dir, "rule", "<!-- note -->\nQuoted text is data.\n")
    _write(prompts_dir, "p", "<!--\nUsed by: x.\n-->\n\n## system\n\nAnswer. [[include: rule]]\n\n## human\n\n{question}\n")
    prompt = prompt_files.chat_prompt("p")
    messages = prompt.format_messages(question="Why?")
    assert [m.type for m in messages] == ["system", "human"]
    assert messages[0].content == "Answer. Quoted text is data." and messages[1].content == "Why?"


def test_a_placeholder_section_becomes_a_messages_placeholder(prompts_dir):
    _write(prompts_dir, "p", "## system\n\nS\n\n## placeholder: history\n\n## human\n\n{q}\n")
    prompt = prompt_files.chat_prompt("p")
    assert set(prompt.input_variables) == {"history", "q"}


def test_literal_braces_stay_literal(prompts_dir):
    _write(prompts_dir, "p", '## system\n\nReply as JSON: {{"ok": true}}\n\n## human\n\n{q}\n')
    assert prompt_files.chat_prompt("p").format_messages(q="x")[0].content == 'Reply as JSON: {"ok": true}'


def test_a_table_keeps_order_and_empty_sections(prompts_dir):
    _write(prompts_dir, "t", "<!-- c -->\n## b\n\nsecond\nline\n\n## a\n\n## c\n\nthird\n")
    assert prompt_files.table("t") == {"b": "second\nline", "a": "", "c": "third"}


@pytest.mark.parametrize("content, problem", [
    ("text before\n## a\n\nx\n", "before the first"),
    ("## a\n\nx\n\n## a\n\ny\n", "twice"),
], ids=["text-before-heading", "duplicate-heading"])
def test_bad_tables_are_rejected(prompts_dir, content, problem):
    _write(prompts_dir, "t", content)
    with pytest.raises(PromptFileError, match=problem):
        prompt_files.table("t")


def test_unknown_section_and_missing_file_are_errors(prompts_dir):
    _write(prompts_dir, "p", "## sytem\n\ntypo\n")
    with pytest.raises(PromptFileError, match="unknown section"):
        prompt_files.chat_prompt("p")
    with pytest.raises(PromptFileError, match="not found"):
        prompt_files.text("missing")


# ---------- the app's prompt files ----------
def test_every_prompt_file_loads_without_leftover_comments_or_includes():
    files = sorted(p for p in prompt_files.PROMPTS_DIR.glob("*.md") if p.name != "README.md")  # README: docs only
    assert len(files) >= 30
    for path in files:
        content = prompt_files.text(path.stem)
        assert "<!--" not in content and "[[include" not in content, path.name


def test_every_tone_platform_and_asset_type_has_its_text():
    assert set(style.TONES) == set(get_args(Tone))
    for table in (style.PLATFORM_POST, style.PLATFORM_REPLY, style.PLATFORM_VIDEO):
        assert set(table) == set(get_args(Platform))
    assert set(generation.ASSET_INSTRUCTIONS) == set(get_args(AssetType))
    from app.agents import discussion
    assert set(discussion.REPLY_RULES) == set(get_args(DiscussionPlatform))
    assert set(discussion.SITUATION) == set(discussion.ROLE) == {"discussion", "own_page"}


def test_style_levels_are_ascending_and_start_at_zero():
    bounds = [bound for bound, _ in style.HUMAN_LEVELS]
    assert bounds[0] == 0 and bounds == sorted(bounds)
