<!--
Extracts book, chapter and page filters from a question (structured retrieval).
Used by: rag/filters.py (FILTER_PROMPT).
Placeholders (filled in by the code): {books}, {question}.
-->

## system

Read the user's question about a library of books and extract the metadata filters it states explicitly, for a search in the books. Only extract what the question says; leave a field empty when it is not mentioned. Never guess a book or chapter from the topic alone.

Books in the library:
{books}

## human

{question}
