"""Fixtures for conversation and chat tests: an authenticated app and a scriptable provider."""

from app.main import app
from app.services.llm.registry import get_registry
from tests.auth_helpers import AuthTestCase
from tests.helpers import fake_provider, make_registry


class ChatTestCase(AuthTestCase):
    def setUp(self):
        super().setUp()
        self.provider = fake_provider()
        self.registry = make_registry(self.provider)
        app.dependency_overrides[get_registry] = lambda: self.registry
        self.alice = self.add_user("alice@example.com")
        self.bob = self.add_user("bob@example.com")

    def as_user(self, user) -> dict[str, str]:
        return self.headers(user)

    def chat(self, user, message="hello", **body):
        return self.client.post(
            "/chat", json={"message": message, **body}, headers=self.as_user(user)
        )

    def conversation_ids(self, user) -> list[str]:
        rows = self.client.get("/conversations", headers=self.as_user(user)).json()
        return [row["id"] for row in rows]
