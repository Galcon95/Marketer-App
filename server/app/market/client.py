"""The app as an MCP client: connects to our MCP servers over Streamable HTTP, like any outside client.

    GUI (Market Intelligence: server cards, tool console, call log)
        │  GET /mcp-servers, POST /mcp-servers/{name}/call  (api/mcp_console.py)
        ▼
    server_status / call_tool   (this module, official mcp SDK Client)
        │  Streamable HTTP: http://127.0.0.1:<port><path>
        ▼
    mcp-book-knowledge (/mcp), mcp-guardrails (/guardrails/mcp)   (mounted in this same API, see server.py)

The calls really go over HTTP and the MCP protocol (initialize, tools/list, tools/call), so the console
shows exactly what an outside client such as Claude Desktop would get. SERVERS is the single list of
servers the GUI shows; remove an entry to hide a server from the GUI (its endpoint stays up for outside
clients). Each request opens a fresh connection: the servers are stateless, and it keeps errors local.
The last CALL_LOG_SIZE calls are kept in memory for the call log (lost on restart).
"""

import json
import logging
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Literal

import anyio
from mcp import Client

from app.core import state as db
from app.core.schemas import McpCallResult, McpServerStatus, McpTool

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ServerConfig:
    """An MCP server the GUI shows."""

    name: str
    path: str  # endpoint path in this API
    audience: Literal["external", "internal"]


SERVERS = [
    ServerConfig(name="mcp-book-knowledge", path="/mcp", audience="external"),
    ServerConfig(name="mcp-guardrails", path="/guardrails/mcp", audience="internal"),
]

LIST_TIMEOUT = 10  # seconds to connect and list a server's tools
CALL_TIMEOUT = 120  # seconds for one tool call (ask_book makes a model call)
MAX_ARGUMENTS_CHARS = 250_000  # size limit of a call's arguments as JSON
CALL_LOG_SIZE = 50

# Recent calls, newest first.
CALL_LOG: deque[McpCallResult] = deque(maxlen=CALL_LOG_SIZE)


class UnknownServerError(KeyError):
    """No server with this name in SERVERS."""


def server_config(name: str) -> ServerConfig:
    """The configured server with this name, or UnknownServerError."""
    for config in SERVERS:
        if config.name == name:
            return config
    raise UnknownServerError(name)


async def server_status(base_url: str, config: ServerConfig) -> McpServerStatus:
    """Connect to a server and list its tools; 'offline' with the error if that fails.

    Args:
        base_url: Where this API is reachable, e.g. "http://127.0.0.1:8000".
        config: The server to check.
    """
    url = base_url + config.path
    started = time.perf_counter()
    try:
        with anyio.fail_after(LIST_TIMEOUT):
            async with Client(url) as client:
                listing = await client.list_tools()
                info = client.server_info
                instructions = client.instructions
    except Exception as e:  # unreachable, timeout, protocol error: show it on the card
        logger.warning("MCP server %s is offline: %s", config.name, e)
        return McpServerStatus(name=config.name, url=url, audience=config.audience, status="offline",
                               error=_error_text(e))
    tools = [
        McpTool(name=t.name, title=t.title, description=t.description or "", input_schema=t.input_schema,
                read_only=t.annotations.read_only_hint if t.annotations else None)
        for t in listing.tools
    ]
    return McpServerStatus(
        name=config.name, title=info.title if info else None, description=info.description if info else None,
        url=url, audience=config.audience, status="active", latency_ms=_ms(started), instructions=instructions,
        tools=tools,
    )


async def call_tool(base_url: str, config: ServerConfig, tool: str, arguments: dict[str, Any]) -> McpCallResult:
    """Call one tool of a server and log the call. Failures (tool errors, timeouts, connection problems)
    are returned as a result with ok=False, not raised, so the console can show them.

    Raises:
        ValueError: If the arguments are larger than MAX_ARGUMENTS_CHARS.
    """
    if len(json.dumps(arguments)) > MAX_ARGUMENTS_CHARS:
        raise ValueError(f"The arguments are too large (at most {MAX_ARGUMENTS_CHARS} characters as JSON).")
    started, called_at = time.perf_counter(), db.now()
    ok, structured, text = False, None, ""
    try:
        with anyio.fail_after(CALL_TIMEOUT):
            async with Client(base_url + config.path) as client:
                result = await client.call_tool(tool, arguments)
        ok = not result.is_error
        structured = result.structured_content
        text = "\n".join(c.text for c in result.content if getattr(c, "type", None) == "text")
    except TimeoutError:
        text = f"The call took longer than {CALL_TIMEOUT} seconds and was stopped."
    except Exception as e:
        logger.warning("MCP call %s/%s failed: %s", config.name, tool, e)
        text = _error_text(e)
    entry = McpCallResult(id=db.new_id("call"), server=config.name, tool=tool, arguments=arguments, ok=ok,
                          structured=structured, text=text, duration_ms=_ms(started), called_at=called_at)
    CALL_LOG.appendleft(entry)
    return entry


def _ms(started: float) -> int:
    """Milliseconds since `started` (a time.perf_counter() value)."""
    return round((time.perf_counter() - started) * 1000)


def _error_text(error: BaseException) -> str:
    """A readable message for a connection or protocol error; exception groups (anyio task groups) are unpacked."""
    while isinstance(error, BaseExceptionGroup) and error.exceptions:
        error = error.exceptions[0]
    return str(error) or type(error).__name__
