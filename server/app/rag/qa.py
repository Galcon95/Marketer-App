"""Question answering over the project's books with LangGraph + LangChain ("ask your book"), with
conversation history.

    START ─(history?)─► condense ─► retrieve ─► answer ─► END
              └─────(first question)──┘

    condense  only for follow-ups: the chat model rewrites the latest question into a standalone search
              question using the recent turns ("and in chapter 3?" → "What does chapter 3 say about ...?")
    retrieve  the (standalone) question is embedded; the k most similar passages come from Chroma (vectorstore.py)
    answer    ChatPromptTemplate: recent turns as chat messages + question + book background (summary.py)
              + numbered passages → ChatOpenAI (via OpenRouter) writes an answer from the passages only, citing them as [n]

Like NotebookLM, the answer is grounded: it may only use the retrieved passages and says so when
they do not answer the question. The history only helps to understand the question; earlier answers
are not a source. Only the passages actually cited are returned as citations (renumbered [1], [2], ...);
all retrieved passages are returned too, so the user can inspect them. Runs are traced in LangSmith as
"answer_question" when tracing is on. Storing the turns of a conversation is up to the caller (api/knowledge.py).
"""

import logging
import re
from functools import cache
from typing import TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langgraph.graph import END, START, StateGraph

from app.core.config import LLM_MODEL
from app.core.llm import GenerationError, chat_model, is_configured, tokens_used
from app.core.schemas import AskResponse, ChatTurn, Chunk, Citation, SearchHit
from app.rag import vectorstore
from app.rag.retrieval import format_background, format_context, keep_cited, retrieve_chunks

logger = logging.getLogger(__name__)

HISTORY_TURNS = 4  # how many earlier turns the model sees (older ones are left out to keep prompts small)
HISTORY_ANSWER_CHARS = 1200  # earlier answers are shortened to this length in the prompt

QA_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "You are a knowledgeable research assistant who answers questions about the user's books.\n"
     "Answer using ONLY the numbered source passages; the book background only helps you understand the "
     "overall context. Cite every passage you use with its number in square brackets, e.g. [2], right after "
     "the statement it supports. Start with a direct answer, then explain in short paragraphs; quote the book "
     "briefly when it helps. Write plain text without Markdown (no **, no #); for lists, start lines with '• '.\n"
     "Earlier turns of the conversation may come before the question: use them to understand what the user "
     "refers to, but they are not a source; cite only the numbered passages given with the current question.\n"
     "If the passages do not answer the question, say so honestly and mention what they do cover instead. "
     "Never guess and never use outside knowledge."),
    MessagesPlaceholder("history"),
    ("human", "Question: {question}\n\nBook background:\n{background}\n\nSource passages:\n\n{context}"),
])

CONDENSE_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "You turn the user's latest message in a conversation about books into a standalone search question. "
     "Use the conversation only to resolve what the message refers to (pronouns, 'that chapter', 'the second "
     "point', 'and what about ...'). Keep the user's language and intent; do not answer it and add nothing new. "
     "If the message is already standalone, return it unchanged. Reply with the question only."),
    ("human", "Conversation so far:\n{history}\n\nLatest message: {question}"),
])


class _QAState(TypedDict, total=False):
    """State of the question-answering graph."""

    project_id: str
    question: str
    history: list[ChatTurn]  # earlier turns of the conversation, oldest first; empty for a first question
    k: int
    source_ids: list[str] | None
    operation: str  # name in the usage log, e.g. "ask" (GUI) or "mcp_ask_book" (MCP)
    search_query: str  # what retrieval searches for: the question, or its standalone rewrite
    context: list[tuple[Chunk, float]]  # retrieved passages with similarity, best first
    answer: str
    citations: list[Citation]
    tokens: int


# ---------- Public API ----------
def answer_question(project_id: str, question: str, k: int, source_ids: list[str] | None = None,
                    operation: str = "ask", history: list[ChatTurn] | None = None) -> AskResponse:
    """Answer a question from the project's books.

    Args:
        project_id: Project whose books to use.
        question: The user's question.
        k: Number of passages to retrieve as context.
        source_ids: Optional filter: only use these sources.
        operation: Name of the caller in the usage log ("ask" for the GUI, "mcp_ask_book" for MCP).
        history: Earlier turns of the conversation, oldest first; the last HISTORY_TURNS are used.
            None or empty = a first question (no rewrite step).

    Returns:
        The answer with the query that was searched, its cited passages, all retrieved passages and token usage.

    Raises:
        GenerationError: 503 if no API key is configured, 409 if there is nothing to search,
            502 if retrieval or the model call fails.
    """
    if not is_configured():
        raise GenerationError(503, "No API key set. Add OPENROUTER_API_KEY (or OPENAI_API_KEY) and restart the server.")
    try:
        state = _graph().invoke(
            {"project_id": project_id, "question": question, "history": (history or [])[-HISTORY_TURNS:], "k": k,
             "source_ids": source_ids, "operation": operation},
            config={"run_name": "answer_question", "tags": ["qa"],
                    "metadata": {"project_id": project_id, "llm_model": LLM_MODEL, "operation": operation}},
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
        search_query=state["search_query"],
        answer=state["answer"],
        citations=state["citations"],
        passages=[SearchHit(chunk=chunk, score=score) for chunk, score in state["context"]],
        model=LLM_MODEL,
        tokens=state["tokens"],
    )


# ---------- Graph ----------
@cache
def _graph():
    """Build and compile the LangGraph: START → (condense →) retrieve → answer → END."""
    builder = StateGraph(_QAState)
    builder.add_node("condense", _condense)
    builder.add_node("retrieve", _retrieve)
    builder.add_node("answer", _answer)
    builder.add_conditional_edges(START, lambda s: "condense" if s.get("history") else "retrieve",
                                  {"condense": "condense", "retrieve": "retrieve"})
    builder.add_edge("condense", "retrieve")
    builder.add_edge("retrieve", "answer")
    builder.add_edge("answer", END)
    return builder.compile()


def _condense(state: _QAState) -> _QAState:
    """Condense node (follow-ups only): rewrite the question into a standalone search question.

    Low temperature, because the rewrite should be faithful, not creative. Falls back to the original
    question if the model returns nothing.
    """
    history = "\n\n".join(f"User: {t.question}\nAssistant: {_plain(t.answer, 600)}" for t in state["history"])
    reply = (CONDENSE_PROMPT | chat_model(0.0)).invoke({"history": history, "question": state["question"]})
    query = str(reply.content).strip().strip('"') or state["question"]
    return {"search_query": query, "tokens": tokens_used(reply)}


def _retrieve(state: _QAState) -> _QAState:
    """Retrieval node: the k passages most similar to the (standalone) question.

    Raises:
        GenerationError: 409 if the project has no searchable passages.
    """
    query = state.get("search_query") or state["question"]
    context = retrieve_chunks(state["project_id"], query, state["k"], state.get("source_ids"),
                              operation=state.get("operation", "ask"))
    if not context:
        raise GenerationError(409, "No searchable books in this project yet. Upload and process a book first.")
    return {"search_query": query, "context": context}


def _answer(state: _QAState) -> _QAState:
    """Answer node: fill the prompt (recent turns, question, background, numbered passages), call the model,
    keep the cited passages."""
    context = state["context"]
    reply = (QA_PROMPT | chat_model()).invoke({
        "history": _history_messages(state.get("history", [])), "question": state["question"],
        "background": format_background(context), "context": format_context(context),
    })
    cited = keep_cited(str(reply.content).strip(), context)
    return {"answer": cited["text"], "citations": cited["citations"],
            "tokens": state.get("tokens", 0) + tokens_used(reply)}


# ---------- Helpers ----------
def _history_messages(history: list[ChatTurn]) -> list[BaseMessage]:
    """Earlier turns as chat messages for the answer prompt; answers without their [n] markers, which
    referred to other passages, and shortened to HISTORY_ANSWER_CHARS."""
    messages: list[BaseMessage] = []
    for turn in history:
        messages += [HumanMessage(turn.question), AIMessage(_plain(turn.answer, HISTORY_ANSWER_CHARS))]
    return messages


def _plain(answer: str, limit: int) -> str:
    """An earlier answer without [n] citation markers, cut to `limit` characters."""
    text = re.sub(r"\s*\[\d+\]", "", answer)
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + " …"
