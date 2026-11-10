# Prompts

Every text the app sends to a language model as instructions is kept here, one Markdown file per prompt, instead of
in the Python code. The loader is `app/core/prompt_files.py`.

## File kinds

| Kind | Format | Read with |
|---|---|---|
| Chat prompt | `## system`, `## human` (and `## placeholder: history` for a list of chat messages) | `prompt_files.chat_prompt("qa_answer")` |
| Table | one `## <key>` section per entry (e.g. per tone or platform); a section may be empty | `prompt_files.table("tones")` |
| Text | the whole file | `prompt_files.text("untrusted_rule")` |

## Rules

- `{name}` is a placeholder the code fills in; write `{{` and `}}` for literal braces (LangChain template syntax).
- `<!-- ... -->` comments are notes for developers (where the prompt is used, what its placeholders mean). They are
  removed and never reach the model.
- `[[include: untrusted_rule]]` inserts another file, e.g. the shared rule that quoted text is data, never instructions.
- Leading and trailing blank lines are ignored; everything else is sent exactly as written.

## After a change

- The dev server reloads by itself. With `uv run fastapi run`, restart it.
- The prompt version of the feature (`qa@…`, `generation@…`, `discussion@…`, …) changes automatically, because it is
  a hash of the loaded prompt text. Results are saved with their version, and the evals show where it changed.
- Run `uv run pytest`. `tests/test_prompt_files.py` checks that every file loads and every tone, platform and asset
  type has its text.
- Re-run the evals (`eval/`) to measure the effect on quality.

## What is not here, and why

- **Pydantic `Field(description=...)`** of the structured-output schemas: they are part of the schema the model fills
  in, so they stay next to the fields they describe.
- **Tool descriptions** (the docstrings of the `@tool` functions in `rag/chat_tools.py` and
  `agents/discussion_tools.py`, and the MCP tools): LangChain and the MCP SDK build the tool schema from the function
  itself.
- **Small labels** that join values into a human message in code (e.g. `Brief: …`, `My angle: …`).

## Files

| Feature | Files |
|---|---|
| Shared | `untrusted_rule`, `injection_note` |
| Ask your book | `qa_answer`, `qa_tools_note`, `qa_condense`, `qa_filters` |
| Book summaries | `summary_chapter`, `summary_book` |
| Generator | `generation_grounded`, `generation_zero_shot`, `generation_plan_query`, `generation_asset_types`, `generation_format_examples` |
| Style and platforms | `style_rewrite`, `style_levels`, `style_avoid_phrases`, `platform_posts`, `platform_replies`, `platform_videos`, `tones` |
| Campaign kit | `campaign_personas`, `campaign_audience`, `campaign_posts`, `campaign_blurb` |
| Discussion Relevance Agent | `discussion_research`, `discussion_assess`, `discussion_draft`, `discussion_reply_rules`, `discussion_situation`, `discussion_role` |
| Reddit scan | `discussion_scan_triage` |
