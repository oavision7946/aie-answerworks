"""Liveness and readiness, both open (no token) and free of internal detail.

- GET /health        is the process answering? Never touches the database; use it for restarts.
- GET /health/ready  can it serve requests? Database reachable and migrated, pgvector installed,
                     JWT secret set and at least one model provider loaded. 503 when not.

The detailed view for dashboards is GET /admin/status (administrators) and GET /metrics.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import Engine

from app.core.settings import Settings, get_settings
from app.db.session import get_engine
from app.schemas.status import Readiness
from app.services import status_service
from app.services.llm.registry import ProviderRegistry, get_registry

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    """200 while the API process is running."""
    return {"status": "ok"}


@router.get("/health/ready", response_model=Readiness, responses={503: {"model": Readiness}})
def ready(
    engine: Annotated[Engine, Depends(get_engine)],
    settings: Annotated[Settings, Depends(get_settings)],
    registry: Annotated[ProviderRegistry, Depends(get_registry)],
) -> JSONResponse:
    """200 when every dependency the API needs is in place, 503 with the failing checks if not."""
    result = status_service.readiness(engine, settings, registry)
    return JSONResponse(
        status_code=200 if result.status == "ok" else 503, content=result.model_dump()
    )
