"""Import every model here so Base.metadata (and Alembic autogenerate) sees all tables."""

from app.db.models.conversation import Conversation, Message, MessageRole
from app.db.models.user import Role, User

__all__ = ["Conversation", "Message", "MessageRole", "Role", "User"]
