"""Knowledge Hub (RAG): book summaries, ask your book (with conversations), semantic search and claim verification."""

import logging
import re

from fastapi import APIRouter, HTTPException

from app.api.deps import get_project_or_404, get_source_or_404, retrieve
from app.core import guard, storage
from app.core import state as db
from app.core.llm import GenerationError
from app.core.schemas import (
    AskRequest, AskResponse, BookSummary, ChatTurn, Conversation, ConversationInfo, SearchHit, SearchRequest,
    SearchResponse, VerifyItem, VerifyRequest, VerifyResponse,
)
from app.rag import qa, summary

logger = logging.getLogger(__name__)
router = APIRouter()

MAX_TURNS = 50  # turns per conversation; after that the user starts a new chat


# Minimum similarity for a claim to count as verified by a source chunk (cosine similarity, 0-1).
VERIFY_MIN_SCORE = 0.5


@router.get("/sources/{source_id}/summary", response_model=BookSummary)
def get_summary(source_id: str):
    """Return the saved summary of a book.

    Args:
        source_id: Id of the source (path parameter). 404 if unknown.

    Raises:
        HTTPException: 404 if the source is unknown or has no summary yet.
    """
    get_source_or_404(source_id)
    found = db.summaries.get(source_id)
    if found is None:
        raise HTTPException(404, "No summary yet")
    return found


@router.post("/sources/{source_id}/summary", response_model=BookSummary, status_code=201)
def create_summary(source_id: str):
    """Create (or recreate) the summary of a processed book: chapter summaries + book overview.

    Runs the LangGraph map-reduce in summary.py over all of the book's chunks, which takes some
    seconds (one model call per chapter, in parallel, plus one to combine). The result is saved and
    then used as background in grounded generation.

    Args:
        source_id: Id of the source (path parameter). 404 if unknown.

    Returns:
        The new summary.

    Raises:
        HTTPException: 409 if the book is not processed ("ready"); 503 if no API key is configured;
            502 if a model call fails.
    """
    source = get_source_or_404(source_id)
    if source.status != "ready":
        raise HTTPException(409, f"'{source.filename}' must be processed (status ready) before it can be summarized")
    try:
        return summary.summarize_source(source)
    except GenerationError as e:
        raise HTTPException(e.status_code, str(e)) from e
    except OSError as e:
        raise HTTPException(500, "The summary was created but could not be saved") from e


@router.post("/projects/{project_id}/ask", response_model=AskResponse)
def ask(project_id: str, body: AskRequest):
    """Answer a question from the project's books, NotebookLM-style, as one turn of a conversation.

    The question is cleaned and checked first (guard.py): too long → 422, likely prompt injection → 400.
    Then the LangGraph in qa.py runs: a follow-up is rewritten into a standalone question with the help of
    the recent turns, the k most similar passages are retrieved, and the LLM answers from those passages
    only (plus the book summary as background), citing them as [n]. The turn is appended to the
    conversation (a new one if conversation_id is empty) and saved to disk.

    Args:
        project_id: Id of the project (path parameter). 404 if unknown.
        body: The question, number of passages k, optional source filter and optional conversation_id.

    Returns:
        The answer with the searched query, its cited passages, all retrieved passages, token usage and
        the conversation id to send with the next question.

    Raises:
        HTTPException: 400 for a likely prompt injection; 404 for an unknown conversation; 409 if there is
            nothing to search or the conversation is full; 422 for an empty or too long question;
            503 if no API key is configured; 502 if retrieval or the model call fails.
    """
    get_project_or_404(project_id)
    question = _checked_question(body.question)
    conversation = _get_conversation_or_404(body.conversation_id) if body.conversation_id else None
    if conversation and conversation.project_id != project_id:
        raise HTTPException(404, f"Conversation '{conversation.id}' not found")
    if conversation and len(conversation.turns) >= MAX_TURNS:
        raise HTTPException(409, f"This chat has reached {MAX_TURNS} questions. Start a new chat to continue.")
    try:
        result = qa.answer_question(project_id, question, body.k, body.source_ids,
                                    history=conversation.turns if conversation else None)
    except GenerationError as e:
        raise HTTPException(e.status_code, str(e)) from e

    now = db.now()
    if conversation is None:
        title = question if len(question) <= 80 else question[:80].rsplit(" ", 1)[0] + " …"
        conversation = Conversation(id=db.new_id("cnv"), project_id=project_id, title=title, created_at=now, updated_at=now)
    result.conversation_id = conversation.id
    conversation.turns.append(ChatTurn(**result.model_dump(), created_at=now))
    conversation.updated_at = now
    db.conversations[conversation.id] = conversation
    try:
        storage.write_conversation(conversation)
    except OSError:  # the answer is still returned; the chat just won't survive a restart
        logger.exception("Could not save conversation %s", conversation.id)
    return result


@router.get("/projects/{project_id}/conversations", response_model=list[ConversationInfo])
def list_conversations(project_id: str):
    """The project's "Ask your book" conversations without their turns, most recently used first."""
    get_project_or_404(project_id)
    conversations = sorted((c for c in db.conversations.values() if c.project_id == project_id),
                           key=lambda c: c.updated_at, reverse=True)
    return [ConversationInfo(id=c.id, title=c.title, created_at=c.created_at, updated_at=c.updated_at,
                             turn_count=len(c.turns)) for c in conversations]


@router.get("/conversations/{conversation_id}", response_model=Conversation)
def get_conversation(conversation_id: str):
    """One conversation with all its turns, oldest first. 404 if unknown."""
    return _get_conversation_or_404(conversation_id)


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: str):
    """Delete a conversation and its saved file. 404 if unknown."""
    conversation = _get_conversation_or_404(conversation_id)
    del db.conversations[conversation.id]
    storage.delete_conversation(conversation)


def _get_conversation_or_404(conversation_id: str) -> Conversation:
    """A conversation by id, or HTTPException 404."""
    conversation = db.conversations.get(conversation_id)
    if conversation is None:
        raise HTTPException(404, f"Conversation '{conversation_id}' not found")
    return conversation


def _checked_question(question: str) -> str:
    """The cleaned question (guard.validate_input), or HTTPException: 422 if it is empty or too long,
    400 if it is a likely prompt injection (guard.check_prompt_injection)."""
    checked = guard.validate_input(question, "question")
    if not checked.ok:
        raise HTTPException(422, " ".join(p.message for p in checked.problems if p.severity == "error"))
    report = guard.check_prompt_injection(checked.cleaned)
    if report.risk == "high":
        logger.warning("Blocked question (prompt injection: %s)", ", ".join(f.rule for f in report.findings))
        raise HTTPException(400, "This question looks like an attempt to change the assistant's instructions "
                                 "and was blocked. Please ask about the books.")
    return checked.cleaned


@router.post("/projects/{project_id}/search", response_model=SearchResponse)
def search(project_id: str, body: SearchRequest):
    """Find the passages of a project's sources that best match a query (semantic vector search).

    The query is embedded and compared with the chunk vectors in Chroma; scores are cosine
    similarities (about 0-1, higher is better).

    Args:
        project_id: Id of the project (path parameter). 404 if unknown.
        body: Query text, number of hits k and optional source filter.

    Returns:
        The query and up to k hits, best first.

    Raises:
        HTTPException: 503 if no embedding API key is configured, 502 if the search fails.
    """
    get_project_or_404(project_id)
    hits = [SearchHit(chunk=c, score=score) for c, score in retrieve(project_id, body.query, body.k, body.source_ids)]
    return SearchResponse(query=body.query, hits=hits)


# ---------- Verification ----------
@router.post("/projects/{project_id}/verify", response_model=VerifyResponse)
def verify(project_id: str, body: VerifyRequest):
    """Check each claim (sentence) of a text against the project's sources.

    Splits the text into sentences and searches the best-matching chunk for each one. A sentence
    counts as verified when that chunk's similarity reaches VERIFY_MIN_SCORE. This finds claims that
    are backed by a similar passage; it does not judge whether the claim is logically entailed.

    Args:
        project_id: Id of the project (path parameter). 404 if unknown.
        body: The text to verify.

    Returns:
        One VerifyItem per sentence, in text order.

    Raises:
        HTTPException: 503 if no embedding API key is configured, 502 if the search fails.
    """
    get_project_or_404(project_id)
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", body.text.replace("\n", " ")) if s.strip()]
    items = []
    for sentence in sentences:
        best = retrieve(project_id, sentence, k=1, operation="verify")
        if best and best[0][1] >= VERIFY_MIN_SCORE:
            items.append(VerifyItem(claim=sentence, status="verified", chunk_id=best[0][0].id, score=best[0][1]))
        else:
            items.append(VerifyItem(claim=sentence, status="not_found"))
    return VerifyResponse(items=items)
