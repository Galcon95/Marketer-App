"""Ingestion pipeline built on LangChain: turns an uploaded PDF into searchable chunks
(load → split → embed → save).

    BookLoader (LangChain BaseLoader, wraps PyMuPDFLoader)  →  one Document per chapter
    RecursiveCharacterTextSplitter (token-based)            →  overlapping chunk Documents
    _merge_small_pieces                                     →  no tiny chunks (lone headings)
    _to_chunk                                               →  Chunk records (schemas.py)
    vectorstore.add_chunks (OpenAIEmbeddings → Chroma)      →  vectors for similarity search
    storage.write_chunks                                    →  chunks saved next to the PDF

Runs as a FastAPI background task after an upload, or when the user presses Process / Re-index /
Retry in the GUI. Progress is written to the source record (status "chunking", then "embedding",
each with progress 0-100) so the GUI can poll it and it survives restarts.
"""

import bisect
import logging
import re
import threading
from collections import Counter
from collections.abc import Callable, Iterator
from functools import cache
from pathlib import Path

import pymupdf
import tiktoken
from langchain_community.document_loaders import PyMuPDFLoader
from langchain_core.document_loaders import BaseLoader
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.core import state as db
from app.core import storage
from app.core.schemas import Chunk, ChunkLocation, Source
from app.rag import vectorstore

logger = logging.getLogger(__name__)

CHUNK_TOKENS = 500  # maximum chunk size in tokens
OVERLAP_TOKENS = 80  # tokens shared by neighbouring chunks, so context is not cut off at a boundary
MIN_CHUNK_TOKENS = 50  # smaller pieces (e.g. a lone chapter heading) are merged into the next chunk
TOKEN_ENCODING = "cl100k_base"  # tiktoken encoding used to measure chunk sizes

# Where the splitter may cut, best first: paragraphs, lines, sentence ends, clauses, words, anywhere.
SEPARATORS = ["\n\n", "\n", ". ", "? ", "! ", "; ", ", ", " ", ""]

PROCESSING_STATUSES = {"queued", "transcribing", "chunking", "embedding"}

# PyMuPDF is not thread-safe, so sources are processed one at a time; waiting ones stay "queued".
_ingest_lock = threading.Lock()

COVER_SEARCH_PAGES = 5  # pages searched for an embedded cover picture
COVER_MAX_HEIGHT = 900  # px; larger cover images are scaled down
# Guards replacing db.chunks, which background tasks and requests may do at the same time.
_chunks_lock = threading.Lock()


class IngestionError(Exception):
    """A processing problem whose message is shown to the user as the source's error."""

class _Cancelled(Exception):
    """Raised when the source was deleted while it was being processed."""


# ---------- Public API ----------
def ingest_source(source_id: str) -> None:
    """Process one source: load its PDF as chapter Documents, split them into chunks, and store them.

    Meant to run as a background task after the caller set the source to "queued". Updates the
    source record as it goes ("chunking" → "embedding", each with progress → "ready" with
    chunk_count, or "failed" with an error message). The chunks are embedded into the vector store
    (vectorstore.add_chunks) before they are saved, so "ready" means searchable. Previous chunks of
    the source are replaced only on success. Stops quietly if the source is deleted meanwhile.

    Args:
        source_id: Id of the source to process.
    """
    with _ingest_lock:
        try:
            source = _update(source_id, status="chunking", progress=0, error=None)
            if not vectorstore.is_configured():
                raise IngestionError("No API key for embeddings. Add OPENROUTER_API_KEY (or OPENAI_API_KEY) to server/.env, restart the server and press Retry.")
            loader = BookLoader(
                storage.source_file_path(source),
                on_progress=lambda done: _update_progress(source_id, round(done * 90)),
            )
            sections = loader.load()
            try:
                _make_cover(source)
            except Exception:  # a missing cover must never fail the processing
                logger.warning("Could not create a cover for %s", source_id, exc_info=True)
            pieces = _merge_small_pieces(_splitter().split_documents(sections))
            chunks = [_to_chunk(doc, source_id, n) for n, doc in enumerate(pieces, start=1)]
            if not chunks:
                raise IngestionError("No text found in the PDF. Scanned books need OCR, which is not supported yet.")

            _update(source_id, status="embedding", progress=0, chunk_count=len(chunks))
            vectorstore.add_chunks(source.project_id, source_id, chunks,
                                   on_progress=lambda done: _update_progress(source_id, round(done * 100)))
            storage.write_chunks(source, chunks)
            replace_source_chunks(source_id, chunks)
            # An existing book summary is kept: re-indexing re-cuts the same book, so its content and
            # summary stay valid (no tokens are spent again). "Regenerate" in the GUI rebuilds it on purpose.
            _update(source_id, status="ready", progress=100, chunk_count=len(chunks))
            logger.info("Ingested %s: %d chapters → %d chunks embedded", source_id, len(sections), len(chunks))
        except _Cancelled:
            logger.info("Ingestion of %s stopped: source was deleted", source_id)
            _delete_vectors(source_id)
        except Exception as e:
            expected = isinstance(e, (IngestionError, vectorstore.VectorStoreError))
            if expected:
                logger.warning("Ingestion of %s failed: %s", source_id, e)
            else:
                logger.exception("Ingestion of %s failed", source_id)
            message = str(e) if expected else f"Processing failed: {e}"
            try:
                _update(source_id, status="failed", error=message)
            except (_Cancelled, OSError):
                pass


def restore_sources() -> None:
    """Load uploaded sources, their chunks and book summaries from disk into memory (called once on server startup).

    Sources that were being processed when the server stopped, ready sources whose chunk file is
    missing, and ready sources whose vectors are missing from the vector store (processed before
    embeddings existed, or the embedding model changed) are marked "failed" so the user can press Retry.
    """
    for source in storage.load_sources().values():
        chunks: list[Chunk] = []
        if source.status in PROCESSING_STATUSES:
            source = _mark_failed(source, "Processing was interrupted by a server restart. Press Retry.")
        elif source.status == "ready":
            loaded = storage.load_chunks(source)
            if loaded is None:
                source = _mark_failed(source, "The saved chunks are missing. Press Retry.")
            elif _vector_count(source) not in (None, len(loaded)):
                source = _mark_failed(source, "Not in the vector database yet (or the embedding model changed). Press Retry.")
            else:
                chunks = loaded
        db.sources[source.id] = source
        if chunks:
            replace_source_chunks(source.id, chunks)
        # Saved summaries are loaded for every book (also one that needs a Retry), so they are never paid twice.
        if summary := storage.load_summary(source):
            db.summaries[source.id] = summary


def replace_source_chunks(source_id: str, chunks: list[Chunk]) -> None:
    """Replace all in-memory chunks of a source (pass [] to remove them).

    Builds a new dict and swaps it in, so requests iterating the old dict are never disturbed.
    New chunks are only added while the source still exists.

    Args:
        source_id: Source whose chunks to replace.
        chunks: The new chunks.
    """
    with _chunks_lock:
        kept = {k: c for k, c in db.chunks.items() if c.source_id != source_id}
        if source_id in db.sources:
            kept.update({c.id: c for c in chunks})
        db.chunks = kept


def make_cover(source: Source, timeout: float = 10) -> bool:
    """Create the cover image of a book if it does not exist yet (for books processed before covers existed).

    Waits for the PDF lock, because PyMuPDF must not run in two threads at once.

    Args:
        source: The book.
        timeout: Seconds to wait if a book is being processed right now.

    Returns:
        True if a cover image exists afterwards.
    """
    if storage.cover_path(source).is_file():
        return True
    if not _ingest_lock.acquire(timeout=timeout):
        return False
    try:
        _make_cover(source)
    except Exception:
        logger.warning("Could not create a cover for %s", source.id, exc_info=True)
    finally:
        _ingest_lock.release()
    return storage.cover_path(source).is_file()


def _make_cover(source: Source) -> None:
    """Save the book's cover as storage.cover_path (caller holds _ingest_lock).

    Uses the first large portrait-format picture in the first COVER_SEARCH_PAGES pages (a typical
    scanned or designed cover; the clearly-taller-than-wide rule skips author portraits and
    illustrations), scaled down to at most COVER_MAX_HEIGHT px. Without one, the first page that
    has any content is rendered as the cover.
    """
    with pymupdf.open(storage.source_file_path(source)) as doc:
        pixmap = None
        for page in list(doc)[:COVER_SEARCH_PAGES]:
            for image in page.get_images(full=True):
                xref, width, height = image[0], image[2], image[3]
                if height >= 300 and height >= 1.3 * width:
                    pixmap = pymupdf.Pixmap(doc, xref)
                    break
            if pixmap:
                break
        if pixmap is None:
            page = next((p for p in doc if p.get_text().strip() or p.get_images()), doc[0])
            pixmap = page.get_pixmap(matrix=pymupdf.Matrix(0.8, 0.8))
        if pixmap.n - pixmap.alpha > 3:  # CMYK etc. → RGB, which PNG needs
            pixmap = pymupdf.Pixmap(pymupdf.csRGB, pixmap)
        if pixmap.alpha:
            pixmap = pymupdf.Pixmap(pixmap, 0)  # drop transparency
        while pixmap.height > COVER_MAX_HEIGHT:
            pixmap.shrink(1)  # halves width and height
        pixmap.save(storage.cover_path(source))


def delete_source_data(source: Source) -> None:
    """Remove a source's chunks and summary from memory and its vectors from the vector store (used on delete).

    Args:
        source: The source being deleted (already removed from db.sources).
    """
    replace_source_chunks(source.id, [])
    db.summaries.pop(source.id, None)
    try:
        vectorstore.delete_source(source.project_id, source.id)
    except Exception:
        logger.exception("Could not delete the vectors of %s", source.id)


def count_tokens(text: str) -> int:
    """Token count of a text with TOKEN_ENCODING (the same measure the splitter uses)."""
    return len(_encoding().encode(text))


# ---------- Step 1: load the book (LangChain document loader) ----------
class BookLoader(BaseLoader):
    """LangChain document loader for books: yields one Document per chapter.

    Wraps LangChain's PyMuPDFLoader, which yields one Document per page with hard-wrapped lines,
    and adds what good book chunks need:
      - paragraphs: wrapped lines are joined; a short line ending in punctuation ends a paragraph,
        and paragraphs are separated by a blank line (the splitter's preferred cut point);
      - words hyphenated at a line end are rejoined;
      - short lines repeated on many pages (running headers/footers, page numbers) are dropped;
      - chapters from the PDF's table of contents: a chapter starts at the line matching its
        heading, or at the top of its page if no line matches.

    Each Document's metadata holds "chapter" (title or None before the first chapter) and
    "page_starts": [[offset, page], ...], the text offset where each 1-based page begins, so a
    chunk's page can be found from its start_index.
    """

    def __init__(self, path: Path, on_progress: Callable[[float], None] | None = None):
        """
        Args:
            path: Path of the PDF file.
            on_progress: Optional callback with the fraction of pages read (0.0-1.0).
        """
        self.path = path
        self.on_progress = on_progress

    def lazy_load(self) -> Iterator[Document]:
        """Read the PDF and yield one Document per chapter, in reading order.

        Raises:
            IngestionError: If the file is missing or not a readable PDF.
        """
        pages = self._read_pages()
        width = _typical_line_width(pages)
        repeated = _repeated_lines(pages)
        chapter_starts = _chapter_starts(self._read_toc())

        chapter: str | None = None
        lines: list[tuple[int, str]] = []  # (page, line) of the current chapter
        for page_no, page_lines in pages:
            page_lines = [l for l in page_lines if _repeat_key(l) not in repeated]
            heading_at: dict[int, str] = {}  # line index → chapter starting there
            for title in chapter_starts.get(page_no, []):
                match = next((i for i, l in enumerate(page_lines) if i not in heading_at and _is_heading(l, title)), None)
                if match is None:  # heading not found: chapter starts at the top of the page
                    yield from _section(lines, chapter, width)
                    chapter, lines = title, []
                else:
                    heading_at[match] = title
            for i, line in enumerate(page_lines):
                if i in heading_at:
                    yield from _section(lines, chapter, width)
                    chapter, lines = heading_at[i], []
                lines.append((page_no, line))
        yield from _section(lines, chapter, width)

    def _read_pages(self) -> list[tuple[int, list[str]]]:
        """Load all pages with PyMuPDFLoader as (1-based page number, non-empty stripped lines)."""
        if not self.path.is_file():
            raise IngestionError("The uploaded file is missing on the server. Delete the source and upload it again.")
        pages: list[tuple[int, list[str]]] = []
        try:
            for doc in PyMuPDFLoader(str(self.path), mode="page").lazy_load():
                lines = [l.strip() for l in doc.page_content.splitlines()]
                pages.append((doc.metadata["page"] + 1, [l for l in lines if l]))
                if self.on_progress:
                    self.on_progress(len(pages) / doc.metadata["total_pages"])
        except _Cancelled:
            raise
        except Exception as e:
            raise IngestionError(f"The PDF could not be read: {e}") from e
        return pages

    def _read_toc(self) -> list:
        """The PDF's table of contents as [level, title, page] entries (PyMuPDFLoader does not expose it)."""
        with pymupdf.open(self.path) as doc:
            return doc.get_toc()


def _section(lines: list[tuple[int, str]], chapter: str | None, width: float) -> Iterator[Document]:
    """Turn one chapter's lines into a Document (nothing if it has no text).

    Joins lines into paragraphs (see _ends_paragraph), rejoins words hyphenated at a line end, and
    records the text offset where each page begins.

    Args:
        lines: (page, line) pairs of the chapter in reading order.
        chapter: Chapter title for the metadata.
        width: Typical full line length of the book, in characters.
    """
    text = ""
    page_starts: list[list[int]] = []
    paragraph_ended = False
    for page, line in lines:
        if not text:
            sep = ""
        elif paragraph_ended:
            sep = "\n\n"
        elif text.endswith("-") and line[:1].islower():
            text, sep = text[:-1], ""  # "over-" + "crowded" → "overcrowded"
        else:
            sep = " "
        if not page_starts or page_starts[-1][1] != page:
            page_starts.append([len(text) + len(sep), page])
        text += sep + line
        paragraph_ended = _ends_paragraph(line, width)
    text = text.replace("­", "")  # soft hyphens
    if text.strip():
        yield Document(page_content=text, metadata={"chapter": chapter, "page_starts": page_starts})


def _ends_paragraph(line: str, width: float) -> bool:
    """Guess whether a line is the last line of a paragraph (or a heading).

    Wrapped lines run to (almost) the full width; a paragraph's last line is usually shorter. So a
    line ends a paragraph if it is clearly short (< 50 % of the width), or somewhat short (< 85 %)
    and ends with closing punctuation.
    """
    if len(line) < 0.5 * width:
        return True
    return len(line) < 0.85 * width and bool(re.search(r"[.!?:;\"”’)\]]$", line))


def _typical_line_width(pages: list[tuple[int, list[str]]]) -> float:
    """Length of a full line in this book: the 90th percentile of all line lengths (1 if no text)."""
    lengths = sorted(len(l) for _, lines in pages for l in lines)
    return lengths[int(len(lengths) * 0.9)] if lengths else 1


def _squash(text: str) -> str:
    """Lowercase letters and digits only, for fuzzy comparisons."""
    return re.sub(r"[^0-9a-z]", "", text.lower())


def _repeat_key(line: str) -> str:
    """Key under which repeated header/footer lines compare equal (digits ignored, so page numbers match)."""
    return re.sub(r"\d+", "#", _squash(line)) if len(line) < 100 else ""


def _repeated_lines(pages: list[tuple[int, list[str]]]) -> set[str]:
    """Keys of short lines that appear on at least half of the pages (and at least 3): headers and footers."""
    counts = Counter(key for _, lines in pages for key in {_repeat_key(l) for l in lines} if key)
    threshold = max(3, len(pages) / 2)
    return {key for key, n in counts.items() if n >= threshold}


def _chapter_starts(toc: list) -> dict[int, list[str]]:
    """Find the chapters in a table of contents and the pages they start on.

    The chapter level is the shallowest TOC level with at least 3 entries (level 1 is often just the
    book title), falling back to the shallowest level. Titles are cleaned: line breaks lost in
    headings ("CHAPTER I.THE TOWN") get their space back.

    Args:
        toc: PyMuPDF table of contents, a list of [level, title, page] (page is 1-based, -1 if none).

    Returns:
        Chapter titles by start page, in TOC order.
    """
    if not toc:
        return {}
    counts = Counter(level for level, _, _ in toc)
    level = min((lvl for lvl, n in counts.items() if n >= 3), default=min(counts))
    starts: dict[int, list[str]] = {}
    for lvl, title, page in toc:
        if lvl == level and page > 0:
            title = re.sub(r"\s+", " ", re.sub(r"(?<=[.:;!?])(?=[A-Z])", " ", title)).strip()
            starts.setdefault(page, []).append(title)
    return starts


def _is_heading(line: str, title: str) -> bool:
    """True if a line is (the start of) a chapter heading, e.g. "CHAPTER XIII." for "CHAPTER XIII. THE FUTURE…"."""
    a, b = _squash(line), _squash(title)
    return len(a) >= 4 and (b.startswith(a) or a.startswith(b))


# ---------- Step 2: split into chunks (LangChain text splitter) ----------
@cache
def _encoding() -> tiktoken.Encoding:
    """The tokenizer, loaded on first use (tiktoken downloads it once, then reads it from its cache)."""
    return tiktoken.get_encoding(TOKEN_ENCODING)


@cache
def _splitter() -> RecursiveCharacterTextSplitter:
    """The LangChain splitter: chunks of at most CHUNK_TOKENS tokens with OVERLAP_TOKENS overlap.

    Tries SEPARATORS in order, so it cuts between paragraphs when possible, then between sentences,
    then words. Separators stay at the end of the preceding piece (sentences keep their period).
    add_start_index stores each chunk's character offset in its chapter as metadata "start_index".
    """
    return RecursiveCharacterTextSplitter.from_tiktoken_encoder(
        encoding_name=TOKEN_ENCODING,
        chunk_size=CHUNK_TOKENS,
        chunk_overlap=OVERLAP_TOKENS,
        separators=SEPARATORS,
        keep_separator="end",
        add_start_index=True,
    )


def _merge_small_pieces(docs: list[Document]) -> list[Document]:
    """Merge pieces under MIN_CHUNK_TOKENS into the next piece of the same chapter.

    The splitter cuts at paragraph breaks first, so a heading followed by a paragraph longer than
    CHUNK_TOKENS ends up alone in a tiny chunk. Merging it forward keeps the heading with its text
    (the merged chunk may exceed CHUNK_TOKENS by up to MIN_CHUNK_TOKENS). A small piece at the end
    of a chapter stays as it is.

    Args:
        docs: Split Documents in reading order.

    Returns:
        The Documents with small pieces merged; a merged piece keeps the small piece's start_index.
    """
    merged: list[Document] = []
    carry: Document | None = None  # small piece waiting to be merged into the next one
    for doc in docs:
        if carry is not None:
            if carry.metadata["page_starts"] == doc.metadata["page_starts"]:  # same chapter Document
                text = doc.page_content if doc.page_content.startswith(carry.page_content) \
                    else carry.page_content.rstrip() + "\n\n" + doc.page_content.lstrip()
                doc = Document(page_content=text, metadata={**doc.metadata, "start_index": carry.metadata["start_index"]})
            else:
                merged.append(carry)
            carry = None
        if count_tokens(doc.page_content) < MIN_CHUNK_TOKENS:
            carry = doc
        else:
            merged.append(doc)
    if carry is not None:
        merged.append(carry)
    return merged


def _to_chunk(doc: Document, source_id: str, number: int) -> Chunk:
    """Convert a split Document into a Chunk record.

    The page is the page on which the chunk starts, looked up from its start_index in the chapter's
    page_starts.

    Args:
        doc: A chunk Document from the splitter (metadata: chapter, page_starts, start_index).
        source_id: Source the chunk belongs to; used for the id "chk_<source>_<0001…>".
        number: 1-based position of the chunk in the source.
    """
    starts = doc.metadata["page_starts"]
    index = bisect.bisect_right([offset for offset, _ in starts], doc.metadata.get("start_index", 0)) - 1
    text = doc.page_content.strip()
    return Chunk(
        id=f"chk_{source_id.removeprefix('src_')}_{number:04d}",
        source_id=source_id,
        text=text,
        location=ChunkLocation(chapter=doc.metadata["chapter"], page=starts[max(index, 0)][1]),
        token_count=count_tokens(text),
    )


# ---------- Source record updates ----------
def _update(source_id: str, **fields) -> Source:
    """Change fields of a source, save the record to disk, then publish it in memory.

    Args:
        source_id: Source to update.
        **fields: Source fields to change, e.g. status="ready".

    Returns:
        The updated source.

    Raises:
        _Cancelled: If the source was deleted (before or during the update).
        OSError: If the record cannot be written for another reason.
    """
    current = db.sources.get(source_id)
    if current is None:
        raise _Cancelled
    updated = current.model_copy(update=fields)
    try:
        storage.write_source_meta(updated)
    except OSError:
        if source_id not in db.sources:
            raise _Cancelled from None
        raise
    if source_id not in db.sources:
        raise _Cancelled
    db.sources[source_id] = updated
    return updated


def _update_progress(source_id: str, percent: int) -> None:
    """Report progress, but only in steps of 5 % or more so the record is not rewritten for every page."""
    current = db.sources.get(source_id)
    if current is not None and percent - current.progress >= 5:
        _update(source_id, progress=percent)


def _vector_count(source: Source) -> int | None:
    """Number of stored vectors of a source, or None if the vector store cannot be read (check skipped)."""
    try:
        return vectorstore.count_source(source.project_id, source.id)
    except Exception:
        logger.exception("Could not check the vectors of %s", source.id)
        return None


def _delete_vectors(source_id: str) -> None:
    """Remove vectors of a source that was deleted while being embedded (its project is looked up on disk)."""
    for project_dir in storage.UPLOAD_DIR.glob("*"):
        try:
            vectorstore.delete_source(project_dir.name, source_id)
        except Exception:
            logger.exception("Could not delete the vectors of %s", source_id)


def _mark_failed(source: Source, message: str) -> Source:
    """Return a copy of a source set to "failed" with an error message, saved to disk if possible."""
    failed = source.model_copy(update={"status": "failed", "error": message})
    try:
        storage.write_source_meta(failed)
    except OSError:
        logger.warning("Could not save the failed status of %s", source.id)
    return failed
