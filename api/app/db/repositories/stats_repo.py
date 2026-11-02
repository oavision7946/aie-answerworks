"""Read-only counts for the status page and /metrics."""

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import Chunk, Conversation, Document, Message, User


def _count(db: Session, model: type[Base], *where: ColumnElement[bool]) -> int:
    query = select(func.count()).select_from(model).where(*where)
    return int(db.scalar(query) or 0)


def counts(db: Session) -> dict[str, int]:
    return {
        "users": _count(db, User),
        "active_users": _count(db, User, User.is_active.is_(True)),
        "conversations": _count(db, Conversation),
        "messages": _count(db, Message),
        "documents": _count(db, Document),
        "chunks": _count(db, Chunk),
    }
