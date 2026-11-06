import time
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.responses import RedirectResponse

from app.api import health, metrics
from app.api.errors import register_exception_handlers
from app.api.middleware import RequestContextMiddleware
from app.api.v1 import (
    admin_status,
    admin_users,
    ask,
    auth,
    chat,
    conversations,
    corpora,
    documents,
    monitoring,
    rag,
)
from app.core.config import load_env
from app.core.settings import load_monitoring
from app.core.telemetry import telemetry
from app.core.tracing import configure_logging, init_tracing

load_env()  # LOG_LEVEL may be set in .env
configure_logging()
_monitoring = load_monitoring()
init_tracing(_monitoring.service_names.api, _monitoring.tracing)

# FastAPI opens the server span and its operation spans itself. Its log events carry exception
# messages and stack traces, and `auto_configure` would add exporters from OTEL_* variables; both
# are off, so what is exported is decided by config/monitoring.yaml and the exporter's filter.
app = FastAPI(title="AnswerWorks API", telemetry={"logs": False, "auto_configure": False})
app.add_middleware(RequestContextMiddleware)
register_exception_handlers(app)
app.include_router(health.router)
app.include_router(metrics.router)
app.include_router(admin_status.router)
app.include_router(monitoring.router)
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
    telemetry.request_started()
    try:
        response = await call_next(request)
    finally:
        telemetry.request_finished()
    route = request.scope.get("route")
    path = getattr(route, "path", None)  # the template, so ids never become labels
    telemetry.request(response.status_code, time.perf_counter() - started, path or "unmatched")
    return response


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    """Send browsers that open the bare address to the interactive docs."""
    return RedirectResponse("/docs")
