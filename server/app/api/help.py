"""The user manual (core/manual.py).

    GET /help/manual   the manual as Markdown; open without a sign-in (like the privacy notice, it explains the app
                       before anyone has an account), no model call, nothing personal in it
"""

import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse

from app.core import manual

logger = logging.getLogger(__name__)

open_router = APIRouter()


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
