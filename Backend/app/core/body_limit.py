"""Rejects request bodies above Settings.max_request_body_bytes with 413 before they are parsed.

Pure ASGI (not @app.middleware) so a chunked body without Content-Length is counted as it
streams in, instead of being read into memory first."""

from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.errors import error_body

_PAYLOAD_TOO_LARGE = 413


class _TooLarge(Exception):
    pass


class BodySizeLimitMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        declared = dict(scope["headers"]).get(b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > self.max_bytes:
            await self._reject(send)
            return

        received = 0
        too_large = False
        started = False

        async def limited_receive() -> Message:
            nonlocal received, too_large
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    too_large = True
                    raise _TooLarge
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if too_large:
                return  # FastAPI turned _TooLarge into its own 400; the 413 replaces it below
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _TooLarge:
            pass
        if too_large and not started:
            await self._reject(send)

    async def _reject(self, send: Send) -> None:
        response = JSONResponse(
            error_body("PAYLOAD_TOO_LARGE", f"Request body is larger than {self.max_bytes} bytes"),
            status_code=_PAYLOAD_TOO_LARGE,
        )
        await response({"type": "http"}, _empty_receive, send)


async def _empty_receive() -> Message:
    return {"type": "http.disconnect"}
