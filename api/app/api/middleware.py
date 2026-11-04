"""Pure ASGI middleware, so it also covers the body of streaming responses."""

import re
import uuid

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core import tracing

REQUEST_ID_HEADER = "X-Request-ID"
_SAFE_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")


def new_request_id() -> str:
    return uuid.uuid4().hex


class RequestContextMiddleware:
    """Give each request an id and return it in `X-Request-ID`.

    The id is the caller's `X-Request-ID` when it is short and plain, otherwise a new one. Spans
    and log lines created while the request runs carry it. The ids are also kept in
    `scope["state"]` so handlers that run outside this middleware (unexpected errors) can use them.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        supplied = Headers(scope=scope).get(REQUEST_ID_HEADER, "")
        request_id = supplied if _SAFE_ID.fullmatch(supplied) else new_request_id()

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        with tracing.request_context(request_id) as ids:
            scope.setdefault("state", {})["ids"] = ids
            await self.app(scope, receive, send_with_id)


def request_ids(scope: Scope) -> dict[str, str]:
    """The ids stored by the middleware, for code that runs after its context has been reset."""
    ids = scope.get("state", {}).get("ids")
    if ids is None:
        return {"request_id": tracing.NO_ID, "trace_id": tracing.NO_ID}
    return {"request_id": ids.request_id, "trace_id": ids.trace_id}
