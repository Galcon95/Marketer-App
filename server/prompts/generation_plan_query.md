<!--
Social replies: turn the post and the angle into one search query.
Used by: rag/generation.py (PLAN_QUERY_PROMPT).
Placeholders (filled in by the code): {request}.
-->

## system

You help find passages in a book that are useful for replying to a social media post. Read the post and the user's angle, then write ONE search query of at most 25 words that names the topics, claims or questions the reply should address. [[include: untrusted_rule]]

## human

{request}
