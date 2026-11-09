"""Discussions (Market Intelligence): the Discussion Relevance Agent and its saved results.

    POST   /projects/{id}/discussions   analyse a pasted discussion for one book (runs the agent), save the result
    GET    /projects/{id}/discussions   the saved analyses, newest first
    GET    /discussions/{id}            one analysis
    PATCH  /discussions/{id}            save the author's edited reply
    DELETE /discussions/{id}            delete an analysis
"""

from fastapi import APIRouter, Depends, HTTPException

from app.agents import discussion
from app.agents.discussion_tools import BookNotReady
from app.api.deps import check_sources, checked_optional, checked_text, llm_limits, owned_discussion, owned_project
from app.core import state as db
from app.core.llm import GenerationError
from app.core.schemas import DiscussionAnalysis, DiscussionRequest, DiscussionUpdate
from app.db import records

router = APIRouter()


@router.post("/projects/{project_id}/discussions", response_model=DiscussionAnalysis, status_code=201,
             dependencies=[Depends(owned_project), Depends(llm_limits)])
def analyze(project_id: str, body: DiscussionRequest):
    """Analyse a discussion from another platform for one book with the Discussion Relevance Agent, and save the result.

    The discussion is someone else's text: it is cleaned and length-checked (guard.py, at most 8000 characters) but
    not blocked for prompt injection, because the author does not control it; it reaches the model only as quoted data
    (agents/discussion.py). The angle is the author's own instruction and is checked for prompt injection. Then the
    agent researches the book with its tools, recommends contribute / more_context / skip and, to contribute, drafts
    a reply grounded in the book's passages.

    Args:
        project_id: Id of the project (path parameter). 404 if unknown.
        body: The book, the pasted discussion, its URL and platform, and an optional angle.

    Returns:
        The saved analysis: recommendation, reason, citations, suggested reply, book mention and the agent's trace.

    Raises:
        HTTPException: 400 if the angle is a likely prompt injection; 404 if the book is not in the project; 409 if
            the book is not processed yet; 422 if a text is empty or too long; 429 if a limit is reached; 503 if no
            API key is configured; 502 if the search or a model call fails; 504 if the model timed out; 500 if the
            result cannot be saved.
    """
    check_sources(project_id, [body.source_id])
    body = body.model_copy(update={
        "discussion": checked_text(body.discussion, "discussion", "discussion", check_injection=False),
        "angle": checked_optional(body.angle, "question", "angle"),
    })
    try:
        analysis = discussion.analyze_discussion(project_id, body)
    except BookNotReady as e:
        raise HTTPException(409, "The book must be processed (status ready) before discussions can be analysed "
                                 "for it.") from e
    except GenerationError as e:
        raise HTTPException(e.status_code, str(e)) from e
    try:
        records.save_discussion(analysis)
    except OSError as e:  # DatabaseError
        raise HTTPException(500, "The discussion was analysed but the result could not be saved.") from e
    return analysis


@router.get("/projects/{project_id}/discussions", response_model=list[DiscussionAnalysis],
            dependencies=[Depends(owned_project)])
def list_discussions(project_id: str):
    """The project's saved discussion analyses, newest first.

    Raises:
        HTTPException: 404 if the project is unknown; 500 if the database cannot be read.
    """
    try:
        return records.list_discussions(project_id)
    except OSError as e:  # DatabaseError
        raise HTTPException(500, "The discussion analyses could not be loaded, please try again.") from e


@router.get("/discussions/{discussion_id}", response_model=DiscussionAnalysis)
def get_discussion(analysis: DiscussionAnalysis = Depends(owned_discussion)):
    """One saved discussion analysis. 404 when no analysis of the user has this id."""
    return analysis


@router.patch("/discussions/{discussion_id}", response_model=DiscussionAnalysis)
def update_discussion(body: DiscussionUpdate, analysis: DiscussionAnalysis = Depends(owned_discussion)):
    """Save the author's edited reply (the agent's suggested_reply is kept as it was).

    Raises:
        HTTPException: 404 when no analysis of the user has this id; 422 if the reply is empty or too long; 500 if it
            cannot be saved.
    """
    reply = checked_text(body.reply, "asset_text", "reply", check_injection=False)  # the author's own text, not a prompt
    analysis = analysis.model_copy(update={"reply": reply, "edited": True, "updated_at": db.now()})
    try:
        records.save_discussion(analysis)
    except OSError as e:  # DatabaseError
        raise HTTPException(500, "The edited reply could not be saved.") from e
    return analysis


@router.delete("/discussions/{discussion_id}", status_code=204)
def delete_discussion(analysis: DiscussionAnalysis = Depends(owned_discussion)):
    """Delete a saved discussion analysis.

    Raises:
        HTTPException: 404 when no analysis of the user has this id; 500 if it cannot be deleted.
    """
    try:
        records.delete_discussion(analysis.id)
    except OSError as e:  # DatabaseError
        raise HTTPException(500, "The discussion analysis could not be deleted, please try again.") from e
