import time
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.responses import RedirectResponse

from app.api import health, metrics
from app.api.errors import register_exception_handlers
from app.api.v1 import (
    admin_status,
    admin_users,
    ask,
    auth,
    chat,
    conversations,
    corpora,
    documents,
    rag,
)
from app.core.telemetry import telemetry

app = FastAPI(title="AnswerWorks API")
register_exception_handlers(app)
app.include_router(health.router)
app.include_router(metrics.router)
app.include_router(admin_status.router)
app.include_router(auth.router)
app.include_router(admin_users.router)
app.include_router(ask.router)
app.include_router(conversations.router)
app.include_router(chat.router)
app.include_router(documents.router)
app.include_router(corpora.router)
app.include_router(rag.router)


@app.middleware("http")
async def count_requests(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Feed the request counters behind /admin/status and /metrics."""
    started = time.perf_counter()
    response = await call_next(request)
    telemetry.request(response.status_code, time.perf_counter() - started)
    return response


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    """Send browsers that open the bare address to the interactive docs."""
    return RedirectResponse("/docs")
