import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.core.settings import Settings, get_settings
from app.db.session import get_engine, get_session
from app.services import status_service
from app.services.llm.registry import ProviderRegistry, get_registry

router = APIRouter(tags=["health"])
metrics_scheme = HTTPBearer(auto_error=False, description="The METRICS_TOKEN from .env")


@router.get("/metrics", response_class=PlainTextResponse)
def metrics(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(metrics_scheme)],
    db: Annotated[Session, Depends(get_session)],
    engine: Annotated[Engine, Depends(get_engine)],
    settings: Annotated[Settings, Depends(get_settings)],
    registry: Annotated[ProviderRegistry, Depends(get_registry)],
) -> str:
    """Prometheus text format. Off (404) unless METRICS_TOKEN is set; send it as a bearer token."""
    expected = settings.env.metrics_token
    if not expected:
        raise HTTPException(404, "Not found.")
    given = credentials.credentials if credentials else ""
    if not secrets.compare_digest(given.encode(), expected.encode()):
        raise HTTPException(401, "Invalid metrics token.", headers={"WWW-Authenticate": "Bearer"})
    return status_service.prometheus(db, engine, settings, registry)
