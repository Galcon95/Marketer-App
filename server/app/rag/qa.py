"""Question answering over the project's books with LangGraph + LangChain ("ask your book").

    START ─► retrieve ─► answer ─► END

    retrieve  the question is embedded; the k most similar passages come from Chroma (vectorstore.py)
    answer    ChatPromptTemplate: question + book background (summary.py) + numbered passages
              → ChatOpenAI (via OpenRouter) writes an answer from the passages only, citing them as [n]

Like NotebookLM, the answer is grounded: it may only use the retrieved passages and says so when
they do not answer the question. Only the passages actually cited are returned as citations
(renumbered [1], [2], ...); all retrieved passages are returned too, so the user can inspect them.
Runs are traced in LangSmith as "answer_question" when tracing is on.
"""

import logging
from functools import cache
from typing import TypedDict

from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import END, START, StateGraph

from app.core.config import LLM_MODEL
from app.core.llm import GenerationError, chat_model, is_configured, tokens_used
from app.core.schemas import AskResponse, Chunk, Citation, SearchHit
from app.rag import vectorstore
from app.rag.retrieval import format_background, format_context, keep_cited, retrieve_chunks

logger = logging.getLogger(__name__)

QA_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "You are a knowledgeable research assistant who answers questions about the user's books.\n"
     "Answer using ONLY the numbered source passages; the book background only helps you understand the "
     "overall context. Cite every passage you use with its number in square brackets, e.g. [2], right after "
     "the statement it supports. Start with a direct answer, then explain in short paragraphs; quote the book "
     "briefly when it helps. Write plain text without Markdown (no **, no #); for lists, start lines with '• '.\n"
     "If the passages do not answer the question, say so honestly and mention what they do cover instead. "
     "Never guess and never use outside knowledge."),
    ("human", "Question: {question}\n\nBook background:\n{background}\n\nSource passages:\n\n{context}"),
])


class _QAState(TypedDict, total=False):
    """State of the question-answering graph."""

    project_id: str
    question: str
    k: int
    source_ids: list[str] | None
    context: list[tuple[Chunk, float]]  # retrieved passages with similarity, best first
    answer: str
    citations: list[Citation]
    tokens: int


# ---------- Public API ----------
def answer_question(project_id: str, question: str, k: int, source_ids: list[str] | None = None) -> AskResponse:
    """Answer a question from the project's books.

    Args:
        project_id: Project whose books to use.
        question: The user's question.
        k: Number of passages to retrieve as context.
        source_ids: Optional filter: only use these sources.

    Returns:
        The answer with its cited passages, all retrieved passages and token usage.

    Raises:
        GenerationError: 503 if no API key is configured, 409 if there is nothing to search,
            502 if retrieval or the model call fails.
    """
    if not is_configured():
        raise GenerationError(503, "No API key set. Add OPENROUTER_API_KEY (or OPENAI_API_KEY) and restart the server.")
    try:
        state = _graph().invoke(
            {"project_id": project_id, "question": question, "k": k, "source_ids": source_ids},
            config={"run_name": "answer_question", "tags": ["qa"],
                    "metadata": {"project_id": project_id, "llm_model": LLM_MODEL, "operation": "ask"}},
        )
    except GenerationError:
        raise
    except vectorstore.VectorStoreError as e:
        raise GenerationError(502, str(e)) from e
    except Exception as e:
        logger.exception("Answering failed")
        raise GenerationError(502, f"The language model call failed: {e}") from e
    return AskResponse(
        question=question,
        answer=state["answer"],
        citations=state["citations"],
        passages=[SearchHit(chunk=chunk, score=score) for chunk, score in state["context"]],
        model=LLM_MODEL,
        tokens=state["tokens"],
    )


# ---------- Graph ----------
@cache
def _graph():
    """Build and compile the LangGraph: START → retrieve → answer → END."""
    builder = StateGraph(_QAState)
    builder.add_node("retrieve", _retrieve)
    builder.add_node("answer", _answer)
    builder.add_edge(START, "retrieve")
    builder.add_edge("retrieve", "answer")
    builder.add_edge("answer", END)
    return builder.compile()


def _retrieve(state: _QAState) -> _QAState:
    """Retrieval node: the k passages most similar to the question.

    Raises:
        GenerationError: 409 if the project has no searchable passages.
    """
    context = retrieve_chunks(state["project_id"], state["question"], state["k"], state.get("source_ids"), operation="ask")
    if not context:
        raise GenerationError(409, "No searchable books in this project yet. Upload and process a book first.")
    return {"context": context}


def _answer(state: _QAState) -> _QAState:
    """Answer node: fill the prompt (question, background, numbered passages), call the model, keep the cited passages."""
    context = state["context"]
    reply = (QA_PROMPT | chat_model()).invoke({
        "question": state["question"], "background": format_background(context), "context": format_context(context),
    })
    cited = keep_cited(str(reply.content).strip(), context)
    return {"answer": cited["text"], "citations": cited["citations"], "tokens": tokens_used(reply)}
