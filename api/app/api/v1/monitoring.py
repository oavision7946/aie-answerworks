from typing import Annotated
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.core import grafana_auth
from app.core.permissions import monitoring_user
from app.core.security import MIN_SECRET_LENGTH, TokenError
from app.core.settings import Settings, get_settings
from app.db.models import Role, User
from app.db.repositories import user_repo
from app.db.session import get_engine, get_session
from app.schemas.monitoring import DashboardLink
from app.schemas.status import SystemStatus
from app.services import status_service
from app.services.llm.registry import ProviderRegistry, get_registry

router = APIRouter(prefix="/monitoring", tags=["monitoring"])


@router.get("/status", response_model=SystemStatus)
def monitoring_status(
    db: Annotated[Session, Depends(get_session)],
    engine: Annotated[Engine, Depends(get_engine)],
    settings: Annotated[Settings, Depends(get_settings)],
    registry: Annotated[ProviderRegistry, Depends(get_registry)],
    viewer: Annotated[User, Depends(monitoring_user)],
) -> SystemStatus:
    """The same system status as `/admin/status`, for administrators and monitors."""
    return status_service.system_status(db, engine, settings, registry)


SESSION_COOKIE = "aw_monitoring"
DASHBOARDS = "/monitoring/grafana/"
_LINK_PROBLEM = (
    "The dashboard link is invalid or has expired. Open it again from the Monitoring page."
)
# Headers that describe one hop and are not forwarded. `host`, the cookie jar and any credentials
# are handled separately, and bodies are passed on unencoded.
_HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "content-length",
    "content-encoding",
    "accept-encoding",
    "host",
    "cookie",
    "authorization",
    "x-jwt-assertion",
}


def _monitoring_secret(settings: Settings) -> str:
    secret = settings.env.monitoring_jwt_secret
    if len(secret) < MIN_SECRET_LENGTH:
        raise HTTPException(503, "Dashboard sign-in is not configured on this server.")
    return secret


def _may_view(user: User | None) -> bool:
    return (
        user is not None
        and user.is_active
        and not user.must_change_password
        and user.role in (Role.ADMIN, Role.MONITOR)
    )


@router.post("/token", response_model=DashboardLink)
def dashboard_token(
    settings: Annotated[Settings, Depends(get_settings)],
    viewer: Annotated[User, Depends(monitoring_user)],
) -> DashboardLink:
    """A one-use link, valid for a few minutes, that opens the dashboards in a browser."""
    token = grafana_auth.launch_token(viewer.id, _monitoring_secret(settings))
    base = settings.env.api_public_url.rstrip("/")
    return DashboardLink(
        login_url=f"{base}/monitoring/login?token={quote(token)}",
        expires_in=int(grafana_auth.LAUNCH_TTL.total_seconds()),
    )


@router.get("/login", include_in_schema=False)
def dashboard_login(
    db: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    token: Annotated[str, Query(max_length=2048)],
) -> Response:
    """Trade a dashboard link for a session cookie and move on, so the token leaves the address."""
    secret = _monitoring_secret(settings)
    try:
        user_id = grafana_auth.redeem_launch_token(token, secret)
    except TokenError as exc:
        raise HTTPException(401, _LINK_PROBLEM) from exc
    user = user_repo.get_by_id(db, user_id)
    if not _may_view(user):
        raise HTTPException(403, "Monitoring access is required.")
    response = RedirectResponse(DASHBOARDS, status_code=303)
    response.set_cookie(
        SESSION_COOKIE,
        grafana_auth.session_token(user_id, secret),
        max_age=int(grafana_auth.SESSION_TTL.total_seconds()),
        path="/monitoring",
        httponly=True,
        secure=settings.env.api_public_url.startswith("https://"),
        samesite="strict",
    )
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    return response


def dashboard_viewer(
    db: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    session: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> User:
    """The signed-in monitor behind the cookie, checked against the database on every request."""
    if session is None:
        raise HTTPException(401, _LINK_PROBLEM)
    try:
        user = user_repo.get_by_id(
            db, grafana_auth.session_user_id(session, _monitoring_secret(settings))
        )
    except TokenError as exc:
        raise HTTPException(401, _LINK_PROBLEM) from exc
    if user is None or not _may_view(user):
        raise HTTPException(403, "Monitoring access is required.")
    return user


@router.get("/grafana", include_in_schema=False)
def dashboards_root() -> RedirectResponse:
    return RedirectResponse(DASHBOARDS, status_code=307)


@router.api_route(
    "/grafana/{path:path}",
    methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    include_in_schema=False,
)
async def dashboards(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    viewer: Annotated[User, Depends(dashboard_viewer)],
) -> Response:
    """Pass the request to Grafana as a Viewer. Grafana is not reachable any other way."""
    secret = _monitoring_secret(settings)
    headers = {k: v for k, v in request.headers.items() if k.lower() not in _HOP_BY_HOP}
    headers["host"] = request.headers.get("host", "")
    headers["accept-encoding"] = "identity"
    headers["x-jwt-assertion"] = grafana_auth.grafana_assertion(viewer.email, secret)
    others = [c for c in request.cookies.items() if c[0] != SESSION_COOKIE]
    if others:
        headers["cookie"] = "; ".join(f"{k}={v}" for k, v in others)
    upstream = settings.env.grafana_url.rstrip("/") + request.url.path
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as client:
            reply = await client.request(
                request.method,
                upstream,
                params=request.url.query or None,
                headers=headers,
                content=await request.body(),
            )
    except httpx.HTTPError as exc:
        raise HTTPException(502, "The dashboards are not reachable.") from exc
    response = Response(reply.content, status_code=reply.status_code)
    for name, value in reply.headers.multi_items():
        if name.lower() not in _HOP_BY_HOP:
            response.headers.append(name, value)
    return response
