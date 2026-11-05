"""The sign-in check of the MCP servers (/mcp, /guardrails/mcp): every request needs `Authorization: Bearer <token>`.

Two kinds of token are accepted:
- a personal API key ("mk_...", api_keys.py): how outside clients such as Claude Desktop (via mcp-remote) connect;
- a Supabase access token, like every other API request: how the app's own MCP console (market/client.py) connects,
  forwarding the signed-in user's token.

Anything else gets 401 before the MCP server sees the request. The user is stored in the request's ASGI scope
(scope["state"]["user"], read with user_of) and in the request context of logs.py (for the usage log).
"""

import json
import logging

import anyio
from fastapi import HTTPException
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core import api_keys
from app.core.auth import User, verify_token
from app.core.logs import set_request_user

logger = logging.getLogger(__name__)


async def authenticate(authorization: str) -> User:
    """The user an Authorization header value stands for.

    Raises:
        HTTPException: 401 without a Bearer token, or with a wrong or revoked key or an invalid access token;
            503 when an access token cannot be checked right now (see auth.verify_token).
    """
    scheme, _, token = authorization.partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(401, "An API key is needed: create one under Keys in the app and send it as "
                                 "'Authorization: Bearer mk_...'.")
    if token.startswith(api_keys.PREFIX):
        user = api_keys.user_for(token)
        if user is None:
            raise HTTPException(401, "This API key is not valid (wrong or revoked).")
        return user
    # A Supabase access token; checking it may fetch the signing keys over the network, so not on the event loop.
    return await anyio.to_thread.run_sync(verify_token, token)


class RequireMcpAuth:
    """ASGI wrapper around an MCP server app: lets a request through only with a valid key or access token."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":  # lifespan
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        try:
            user = await authenticate(headers.get("authorization", ""))
        except HTTPException as e:
            logger.info("MCP request to %s refused: %s", scope.get("path"), e.detail)
            await _reject(send, e.status_code, str(e.detail))
            return
        scope.setdefault("state", {})["user"] = user
        set_request_user(user.id)
        await self.app(scope, receive, send)


def user_of(scope: Scope) -> User | None:
    """The user RequireMcpAuth let through for this request (None outside it)."""
    return scope.get("state", {}).get("user")


async def _reject(send: Send, status: int, message: str) -> None:
    """Answer with a JSON error, like the API's other errors ({"detail": ...})."""
    body = json.dumps({"detail": message}).encode("utf-8")
    headers = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]
    if status == 401:
        headers.append((b"www-authenticate", b'Bearer realm="marketer-mcp"'))
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})
