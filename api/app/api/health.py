import logging
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import Engine

from app.db.session import check_database, get_engine

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/health")
def health(engine: Annotated[Engine, Depends(get_engine)]) -> JSONResponse:
    """200 when the API and database are reachable, 503 when the database is not."""
    database_ok = check_database(engine)
    if not database_ok:
        logger.error("Health check failed: database is unreachable")
    return JSONResponse(
        status_code=200 if database_ok else 503,
        content={
            "status": "ok" if database_ok else "degraded",
            "database": "ok" if database_ok else "unavailable",
        },
    )
