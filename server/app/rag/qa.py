"""Question answering over the project's books with LangGraph + LangChain ("ask your book"), with
conversation history and tool calling.

    START ─(history?)─► condense ─► filter ─► retrieve ─► answer ─(tool calls?)─► tools ─► respond ─► END
              └─────(first question)──┘                     └──────(no tool calls)───────────────────►┘

    condense  only for follow-ups: the chat model rewrites the latest question into a standalone search
              question using the recent turns ("and in chapter 3?" → "What does chapter 3 say about ...?")
    filter    structured retrieval (filters.py): if the question names a book, chapter or pages, a model call with
              structured output extracts them and code resolves them to real metadata values ("chapter 17 of
              Butler" → that book, "CHAPTER XVII. SHORT SELLING"); questions without such hints skip the model call
    retrieve  the (standalone) question is embedded; the k most similar passages come from Chroma (vectorstore.py),
              restricted by the filters; if the filters find nothing, it searches again without them
    answer    ChatPromptTemplate: recent turns as chat messages + question + book background (summary.py)
              + numbered passages → ChatOpenAI (via OpenRouter) writes an answer from the passages only, citing them as [n].
              With use_tools (the chat), the model also gets the chat tools (chat_tools.py: list_books,
              check_platform_fit, draft_social_post) and may answer with tool calls instead
    tools     runs the requested tool calls (one round, at most chat_tools.MAX_TOOL_CALLS)
    respond   the model writes the final answer from the passages and the tool results; it can call no
              further tools (tool_choice "none"), so there is never a loop

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
from app.core.guard import UNTRUSTED_RULE
from app.core.llm import GenerationError, chat_model, is_configured, tokens_used
from app.core.schemas import AskResponse, ChatTurn, Chunk, Citation, SearchHit, ToolCallRecord
from app.rag import vectorstore
from app.rag.chat_tools import make_tools, run_tool_calls
from app.rag.filters import ResolvedFilters, extract_filters, might_filter, resolve_filters
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
     "Never guess and never use outside knowledge.\n"
     "The passages come as <passage n=\"...\"> blocks; cite passage n as [n]. " + UNTRUSTED_RULE + "{tools_note}"),
    MessagesPlaceholder("history"),
    ("human", "Question: {question}\n\nBook background:\n{background}\n\nSource passages:\n\n{context}"),
])

# Added to the system prompt when the model gets the chat tools.
TOOLS_NOTE = (
    "\nYou can also call tools, but only when the question needs them: list_books for questions about the "
    "library itself (which books, authors, themes), check_platform_fit to check a post for a social platform, and "
    "draft_social_post when the user asks you to write a post. Questions about what the books say are answered "
    "from the passages, without tools. You may use facts from tool results too; do not put [n] markers on them. "
    "When you present a drafted post, show it in full and mention that it was saved to the asset library."
)

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
    use_tools: bool  # offer the chat tools to the model (the chat yes, MCP's ask_book no)
    search_query: str  # what retrieval searches for: the question, or its standalone rewrite
    filters: ResolvedFilters | None  # book/chapter/page filters taken from the question (structured retrieval)
    filter_note: str  # what was filtered, for the GUI, e.g. "Successful Stock Speculation · CHAPTER XVII. ..."
    context: list[tuple[Chunk, float]]  # retrieved passages with similarity, best first
    messages: list[BaseMessage]  # the answer prompt plus the model's tool calls and their results (tool round only)
    tool_calls: list[ToolCallRecord]  # the tools that ran, for the GUI
    answer: str
    citations: list[Citation]
    tokens: int


# ---------- Public API ----------
def answer_question(project_id: str, question: str, k: int, source_ids: list[str] | None = None,
                    operation: str = "ask", history: list[ChatTurn] | None = None, use_tools: bool = False) -> AskResponse:
    """Answer a question from the project's books.

    Args:
        project_id: Project whose books to use.
        question: The user's question.
        k: Number of passages to retrieve as context.
        source_ids: Optional filter: only use these sources.
        operation: Name of the caller in the usage log ("ask" for the GUI, "mcp_ask_book" for MCP).
        history: Earlier turns of the conversation, oldest first; the last HISTORY_TURNS are used.
            None or empty = a first question (no rewrite step).
        use_tools: Let the model call the chat tools (one round), e.g. to check or draft a post.

    Returns:
        The answer with the query that was searched, its cited passages, all retrieved passages, the tool
        calls made and token usage.

    Raises:
        GenerationError: 503 if no API key is configured, 409 if there is nothing to search,
            502 if retrieval or the model call fails.
    """
    if not is_configured():
        raise GenerationError(503, "No API key set. Add OPENROUTER_API_KEY (or OPENAI_API_KEY) and restart the server.")
    try:
        state = _graph().invoke(
            {"project_id": project_id, "question": question, "history": (history or [])[-HISTORY_TURNS:], "k": k,
             "source_ids": source_ids, "operation": operation, "use_tools": use_tools},
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
        filters=state.get("filter_note", ""),
        answer=state["answer"],
        citations=state["citations"],
        passages=[SearchHit(chunk=chunk, score=score) for chunk, score in state["context"]],
        model=LLM_MODEL,
        tokens=state["tokens"],
        tool_calls=state.get("tool_calls", []),
    )


# ---------- Graph ----------
@cache
def _graph():
    """Build and compile the LangGraph: START → (condense →) filter → retrieve → answer → (tools → respond →) END."""
    builder = StateGraph(_QAState)
    builder.add_node("condense", _condense)
    builder.add_node("filter", _filter)
    builder.add_node("retrieve", _retrieve)
    builder.add_node("answer", _answer)
    builder.add_node("tools", _tools)
    builder.add_node("respond", _respond)
    builder.add_conditional_edges(START, lambda s: "condense" if s.get("history") else "filter",
                                  {"condense": "condense", "filter": "filter"})
    builder.add_edge("condense", "filter")
    builder.add_edge("filter", "retrieve")
    builder.add_edge("retrieve", "answer")
    builder.add_conditional_edges("answer", lambda s: "tools" if s.get("messages") else END, {"tools": "tools", END: END})
    builder.add_edge("tools", "respond")
    builder.add_edge("respond", END)
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


def _filter(state: _QAState) -> _QAState:
    """Filter node (structured retrieval): the book, chapter or pages the (standalone) question names, as metadata
    filters. Skips the model call when the question has no such hints (filters.might_filter)."""
    query = state.get("search_query") or state["question"]
    if not might_filter(state["project_id"], query):
        return {"search_query": query}
    extracted, tokens = extract_filters(state["project_id"], query)
    resolved = resolve_filters(state["project_id"], extracted, state.get("source_ids"))
    note = "; ".join(x for x in [resolved.description, *resolved.notes] if x)
    return {"search_query": query, "filters": resolved, "filter_note": note, "tokens": state.get("tokens", 0) + tokens}


def _retrieve(state: _QAState) -> _QAState:
    """Retrieval node: the k passages most similar to the (standalone) question, within the filters. If the filters
    leave nothing, the search runs again without them (and the note says so), so a filter never empties an answer.

    Raises:
        GenerationError: 409 if the project has no searchable passages.
    """
    query = state.get("search_query") or state["question"]
    filters, note = state.get("filters"), state.get("filter_note", "")
    source_ids = filters.source_ids if filters else state.get("source_ids")
    where = filters.where() if filters else None
    context = retrieve_chunks(state["project_id"], query, state["k"], source_ids, where=where,
                              operation=state.get("operation", "ask"))
    if not context and (where or source_ids != state.get("source_ids")):
        context = retrieve_chunks(state["project_id"], query, state["k"], state.get("source_ids"),
                                  operation=state.get("operation", "ask"))
        note = "; ".join(x for x in [note, "nothing matched the filter, so all passages were searched"] if x)
    if not context:
        raise GenerationError(409, "No searchable books in this project yet. Upload and process a book first.")
    return {"search_query": query, "context": context, "filter_note": note}


def _answer(state: _QAState) -> _QAState:
    """Answer node: fill the prompt (recent turns, question, background, numbered passages) and call the model.

    Without tools, or when the model calls none, its reply is the answer (cited passages kept). When it
    calls tools, the prompt and its reply are kept in "messages" and the graph goes on to the tools node.
    """
    use_tools = state.get("use_tools", False)
    messages = QA_PROMPT.format_messages(
        history=_history_messages(state.get("history", [])), question=state["question"],
        background=format_background(state["context"]), context=format_context(state["context"]),
        tools_note=TOOLS_NOTE if use_tools else "",
    )
    model = chat_model().bind_tools(make_tools(state["project_id"])) if use_tools else chat_model()
    reply = model.invoke(messages)
    tokens = state.get("tokens", 0) + tokens_used(reply)
    if getattr(reply, "tool_calls", None):
        return {"messages": [*messages, reply], "tokens": tokens}
    return {**_final(reply, state["context"]), "tokens": tokens}


def _tools(state: _QAState) -> _QAState:
    """Tools node: run the tool calls of the model's reply; their results are appended as tool messages."""
    tool_messages, records = run_tool_calls(state["project_id"], state["messages"][-1].tool_calls)
    draft_tokens = sum(r.result.get("tokens", 0) for r in records if r.ok and isinstance(r.result, dict))
    return {"messages": [*state["messages"], *tool_messages], "tool_calls": records,
            "tokens": state.get("tokens", 0) + draft_tokens}


def _respond(state: _QAState) -> _QAState:
    """Respond node: the model writes the final answer from the passages and the tool results. The tools stay
    bound (the request contains tool calls) but tool_choice "none" forbids new calls: one round, no loop."""
    model = chat_model().bind_tools(make_tools(state["project_id"]), tool_choice="none")
    reply = model.invoke(state["messages"])
    return {**_final(reply, state["context"]), "tokens": state.get("tokens", 0) + tokens_used(reply)}


# ---------- Helpers ----------
def _final(reply: AIMessage, context: list[tuple[Chunk, float]]) -> _QAState:
    """The answer and its citations from the model's final reply (only the passages it cited are kept)."""
    cited = keep_cited(str(reply.content).strip(), context)
    return {"answer": cited["text"], "citations": cited["citations"]}


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
