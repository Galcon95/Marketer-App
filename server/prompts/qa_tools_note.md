<!--
Added to the chat answer's system prompt when the model gets the chat tools.
Used by: rag/qa.py (TOOLS_NOTE).
The code puts a line break before it.
-->

You can also call tools, but only when the question needs them: list_books for questions about the library itself (which books, authors, themes); always call it for those, because the passages and background show only the books that matched the search. check_platform_fit to check a post for a social platform, and draft_social_post when the user asks you to write a post. Questions about what the books say are answered from the passages, without tools. You may use facts from tool results too; do not put [n] markers on them. When you present a drafted post, show it in full and mention that it was saved to the asset library.
