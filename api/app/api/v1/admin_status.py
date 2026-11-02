from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.core.permissions import admin_user
from app.core.settings import Settings, get_settings
from app.db.models import User
from app.db.session import get_engine, get_session
from app.schemas.status import SystemStatus
from app.services import status_service
from app.services.llm.registry import ProviderRegistry, get_registry

router = APIRouter(prefix="/admin/status", tags=["admin"])


@router.get("", response_model=SystemStatus)
def system_status(
    db: Annotated[Session, Depends(get_session)],
    engine: Annotated[Engine, Depends(get_engine)],
    settings: Annotated[Settings, Depends(get_settings)],
    registry: Annotated[ProviderRegistry, Depends(get_registry)],
    admin: Annotated[User, Depends(admin_user)],
) -> SystemStatus:
    """Database, schema version, providers, embedding models, corpora, counts and request totals."""
    return status_service.system_status(db, engine, settings, registry)
