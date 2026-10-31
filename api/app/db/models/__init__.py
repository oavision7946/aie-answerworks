"""Import every model here so Base.metadata (and Alembic autogenerate) sees all tables."""

from app.db.models.conversation import Conversation, Message, MessageRole
from app.db.models.corpus import Corpus, CorpusAccess
from app.db.models.document import Chunk, Document, DocumentStatus
from app.db.models.user import Role, User

__all__ = [
    "Chunk",
    "Conversation",
    "Corpus",
    "CorpusAccess",
    "Document",
    "DocumentStatus",
    "Message",
    "MessageRole",
    "Role",
    "User",
]
