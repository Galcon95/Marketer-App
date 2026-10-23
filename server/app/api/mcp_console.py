"""Market Intelligence: the MCP console. Lists our MCP servers with their tools, runs tool calls and
keeps a call log. The app talks to the servers as a real MCP client (market/client.py)."""

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.deps import llm_rate_limit

from app.core.schemas import McpCallRequest, McpCallResult, McpServerStatus
from app.market import client

router = APIRouter()


@router.get("/mcp-servers", response_model=list[McpServerStatus])
async def list_mcp_servers(request: Request):
    """All MCP servers the GUI shows, each with its live status and tools (connected in parallel)."""
    base_url = _base_url(request)
    return await asyncio.gather(*(client.server_status(base_url, config) for config in client.SERVERS))


@router.post("/mcp-servers/{name}/call", response_model=McpCallResult, dependencies=[Depends(llm_rate_limit)])
async def call_mcp_tool(name: str, body: McpCallRequest, request: Request):
    """Call a tool of an MCP server over MCP and return its result (also added to the call log).

    A failing call (tool error, timeout, server offline) is returned with ok=false and the error as text.

    Raises:
        HTTPException: 404 for an unknown server; 413 if the arguments are too large; 429 if the rate limit is
            reached (a tool like ask_book calls the model).
    """
    try:
        config = client.server_config(name)
    except client.UnknownServerError as e:
        raise HTTPException(404, f"Unknown MCP server '{name}'") from e
    try:
        return await client.call_tool(_base_url(request), config, body.tool, body.arguments)
    except ValueError as e:
        raise HTTPException(413, str(e)) from e


@router.get("/mcp-calls", response_model=list[McpCallResult])
def list_mcp_calls():
    """The most recent tool calls made from the console, newest first (kept in memory only)."""
    return list(client.CALL_LOG)


def _base_url(request: Request) -> str:
    """This API's own address on localhost (the MCP servers accept only localhost hosts)."""
    return f"http://127.0.0.1:{request.url.port or 8000}"
