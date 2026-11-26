"""Security headers on every response of the server (API and MCP): instructions for the browser that receives it.

    X-Content-Type-Options: nosniff   never guess a file's type (an uploaded file cannot be run as a script)
    X-Frame-Options: DENY             no site may show a response in a frame
    Referrer-Policy: no-referrer      the address of an API request is not passed on to other sites
    Strict-Transport-Security         https only from now on (browsers ignore it on plain http, e.g. localhost)
    Content-Security-Policy           a response opened as a page may load and run nothing; not on FastAPI's own
                                      /docs and /redoc pages, which load their scripts from a CDN
    Cache-Control: no-store           answers hold the user's data (or tokens: POST /guest), so nothing keeps a copy;
                                      only when the endpoint did not set its own (ad pictures, covers)

A header the endpoint set itself is kept. The web client sets its own headers in client/next.config.ts.
"""

HEADERS: dict[bytes, bytes] = {
    b"x-content-type-options": b"nosniff",
    b"x-frame-options": b"DENY",
    b"referrer-policy": b"no-referrer",
    b"strict-transport-security": b"max-age=63072000; includeSubDomains",
    b"cache-control": b"no-store",
}
CSP = (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'")
DOCS_PATHS = ("/docs", "/redoc")  # Swagger UI and ReDoc: HTML pages with scripts from a CDN


class SecurityHeadersMiddleware:
    """ASGI middleware: adds the headers above to every HTTP response that does not have them yet."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        wanted = dict(HEADERS)
        if not scope.get("path", "").startswith(DOCS_PATHS):
            wanted[CSP[0]] = CSP[1]

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {name.lower() for name, _ in headers}
                headers += [(name, value) for name, value in wanted.items() if name not in present]
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)
