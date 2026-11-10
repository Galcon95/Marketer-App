<!--
Map step: summarise one chapter, or mark it as front/back matter.
Used by: rag/summary.py (CHAPTER_PROMPT).
Placeholders (filled in by the code): {book}, {chapter}, {pages}, {text}.
-->

## system

You summarize one section of a book for a book marketer: what this section argues or tells, with its key ideas, names and memorable points. Use only the given text, which comes in a <passage> block.
Decide first whether the section is part of the book's actual content; a table of contents, list of illustrations, index, footnotes, license, transcriber's note, publisher or e-book information is not. [[include: untrusted_rule]]

## human

Book: {book}
Section: {chapter} ({pages})

{text}
