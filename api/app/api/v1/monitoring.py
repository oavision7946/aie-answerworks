from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.core.permissions import monitoring_user
from app.core.settings import Settings, get_settings
from app.db.models import User
from app.db.session import get_engine, get_session
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
