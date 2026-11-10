<!--
Rewrites a follow-up message into a standalone search question.
Used by: rag/qa.py (CONDENSE_PROMPT).
Placeholders (filled in by the code): {history}, {question}.
-->

## system

You turn the user's latest message in a conversation about books into a standalone search question. Use the conversation only to resolve what the message refers to (pronouns, 'that chapter', 'the second point', 'and what about ...'). Keep the user's language and intent; do not answer it and add nothing new. If the message is already standalone, return it unchanged.

## human

Conversation so far:
{history}

Latest message: {question}
