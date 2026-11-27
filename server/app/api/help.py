"""The user manual (core/manual.py) and "Ask the app" (rag/manual_qa.py).

    GET /help/manual   the manual as Markdown; open without a sign-in (like the privacy notice, it explains the app
                       before anyone has an account), no model call, nothing personal in it
    POST /help/ask     a question about using the app, answered from the manual; signed in (the guest too), within
                       the user's model-call limits and budgets, like every model call
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse

from app.api.deps import checked_text, llm_limits
from app.core import manual
from app.core.llm import GenerationError
from app.core.schemas import HelpRequest, HelpResponse, HelpTurn
from app.rag import manual_qa

logger = logging.getLogger(__name__)

open_router = APIRouter()
router = APIRouter()  # included with the sign-in check (server.py)


@router.post("/help/ask", response_model=HelpResponse, dependencies=[Depends(llm_limits)])
def ask(body: HelpRequest) -> HelpResponse:
    """Answer a question about using the app from the manual. Nothing is saved: the browser keeps the chat and
    sends its last turns along.

    The question (and the earlier questions sent along) are checked like every chat message: too long → 422, a
    likely prompt injection → 400. The model has no tools: it can only explain.

    Raises:
        HTTPException: 400 for a likely prompt injection; 422 for an empty or too long question; 429 when the
            rate limit or a budget is reached; 502/504 if the model fails; 503 if the manual is missing.
    """
    question = checked_text(body.question, "question", "question")
    history = [HelpTurn(question=checked_text(t.question, "question", "earlier question"), answer=t.answer)
               for t in body.history]
    try:
        return manual_qa.ask_app(question, body.page, history)
    except GenerationError as e:
        raise HTTPException(e.status_code, str(e)) from e
    except OSError as e:
        logger.error("The manual cannot be read: %s", e)
        raise HTTPException(503, "The manual is not available right now.") from e


@open_router.get("/help/manual", response_class=PlainTextResponse)
def get_manual() -> PlainTextResponse:
    """The manual as Markdown (text/markdown).

    Raises:
        HTTPException: 503 if the manual file is missing on the server.
    """
    try:
        markdown = manual.text()
    except OSError as e:
        logger.error("The manual cannot be read: %s", e)
        raise HTTPException(503, "The manual is not available right now.") from e
    return PlainTextResponse(markdown, media_type="text/markdown; charset=utf-8",
                             headers={"Cache-Control": "public, max-age=300"})
