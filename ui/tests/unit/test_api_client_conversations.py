"""Chat, conversation, current-user and admin-user calls of the API client."""

import json
import unittest

import httpx
import respx

from app import config
from app.clients import api_client
from app.clients.api_client import AuthExpired
from tests.unit.test_api_client import sse

BASE = config.API_BASE_URL.rstrip("/")
GPT = api_client.ModelInfo(provider="openai", id="gpt-4o", label="GPT-4o")
BARE = api_client.ModelInfo(provider="", id="m", label="m")
CHAT = {
    "conversation_id": "c-1",
    "message_id": "m-1",
    "answer": "Hi",
    "provider": "openai",
    "model": "gpt-4o",
    "tokens_used": 5,
    "latency_ms": 3,
    "cost_usd": None,
}
USER = {
    "id": "u-1",
    "email": "ana@example.com",
    "role": "user",
    "is_active": True,
    "must_change_password": False,
}


def sent(route) -> dict:
    return json.loads(route.calls.last.request.content)


class TestChat(unittest.TestCase):
    @respx.mock
    def test_new_conversation_payload_and_token(self):
        route = respx.post(f"{BASE}/chat").respond(json=CHAT)

        result = api_client.chat("hello", GPT, None, token="t")

        self.assertEqual(sent(route), {"message": "hello", "model": "gpt-4o", "provider": "openai"})
        self.assertEqual(route.calls.last.request.headers["authorization"], "Bearer t")
        self.assertEqual((result.conversation_id, result.message_id), ("c-1", "m-1"))

    @respx.mock
    def test_continuing_sends_the_conversation_id_and_omits_an_unknown_provider(self):
        route = respx.post(f"{BASE}/chat").respond(json=CHAT)

        api_client.chat("again", BARE, "c-1", token="t")

        self.assertEqual(sent(route), {"message": "again", "model": "m", "conversation_id": "c-1"})

    @respx.mock
    def test_errors(self):
        route = respx.post(f"{BASE}/chat")
        route.respond(401, json={"detail": "expired"})
        with self.assertRaises(AuthExpired):
            api_client.chat("x", GPT, None)
        route.respond(404, json={"detail": "Conversation not found."})
        with self.assertRaisesRegex(RuntimeError, "Conversation not found."):
            api_client.chat("x", GPT, "c-1")
        route.respond(200, json={"nope": 1})
        with self.assertRaisesRegex(RuntimeError, "unexpected response"):
            api_client.chat("x", GPT, None)
        route.mock(side_effect=httpx.ConnectError("down"))
        with self.assertRaisesRegex(RuntimeError, "Could not reach the API"):
            api_client.chat("x", GPT, None)

    @respx.mock
    def test_error_without_json_body_uses_the_text(self):
        respx.post(f"{BASE}/chat").respond(500, text="boom")

        with self.assertRaisesRegex(RuntimeError, "boom"):
            api_client.chat("x", GPT, None)


class TestChatStreaming(unittest.TestCase):
    @respx.mock
    def test_streams_deltas_and_returns_stored_ids(self):
        route = respx.post(f"{BASE}/chat").respond(
            200,
            text=sse(
                ("delta", {"content": "Hi "}),
                ("delta", {"content": "there"}),
                ("done", {**CHAT, "answer": "Hi there"}),
            ),
        )
        seen: list[str] = []

        result = api_client.chat_streaming("hello", GPT, "c-1", seen.append, token="t")

        self.assertEqual(seen, ["Hi ", "Hi there"])
        self.assertEqual(sent(route)["stream"], True)
        self.assertEqual(sent(route)["conversation_id"], "c-1")
        self.assertEqual(result.message_id, "m-1")

    @respx.mock
    def test_error_event_and_missing_done(self):
        route = respx.post(f"{BASE}/chat")
        route.respond(200, text=sse(("error", {"detail": "Conversation not found."})))
        with self.assertRaisesRegex(RuntimeError, "Conversation not found."):
            api_client.chat_streaming("x", GPT, None, lambda _: None)
        route.respond(200, text=sse(("delta", {"content": "a"})))
        with self.assertRaisesRegex(RuntimeError, "ended before completion"):
            api_client.chat_streaming("x", GPT, None, lambda _: None)

    @respx.mock
    def test_401_and_http_errors(self):
        route = respx.post(f"{BASE}/chat")
        route.respond(401, json={"detail": "expired"})
        with self.assertRaises(AuthExpired):
            api_client.chat_streaming("x", GPT, None, lambda _: None)
        route.respond(404, json={"detail": "Conversation not found."})
        with self.assertRaisesRegex(RuntimeError, "API error \\(404\\)"):
            api_client.chat_streaming("x", GPT, "c", lambda _: None)


class TestConversations(unittest.TestCase):
    @respx.mock
    def test_list(self):
        route = respx.get(f"{BASE}/conversations", params={"limit": 100}).respond(
            json=[{"id": "c-1", "title": "T", "updated_at": "2026-10-30T10:00:00Z"}]
        )

        result = api_client.list_conversations(token="t")

        self.assertEqual([(c.id, c.title, c.model) for c in result], [("c-1", "T", None)])
        self.assertEqual(route.calls.last.request.headers["authorization"], "Bearer t")

    @respx.mock
    def test_list_with_an_unexpected_body(self):
        respx.get(f"{BASE}/conversations").respond(json={"not": "a list"})

        with self.assertRaisesRegex(RuntimeError, "unexpected response"):
            api_client.list_conversations()

    @respx.mock
    def test_get_includes_messages(self):
        respx.get(f"{BASE}/conversations/c-1").respond(
            json={
                "id": "c-1",
                "title": "T",
                "messages": [{"id": "m", "role": "user", "content": "hi"}],
            }
        )

        detail = api_client.get_conversation("c-1")

        self.assertEqual([(m.role, m.content) for m in detail.messages], [("user", "hi")])

    @respx.mock
    def test_rename_and_delete(self):
        rename = respx.patch(f"{BASE}/conversations/c-1").respond(
            json={"id": "c-1", "title": "New"}
        )
        delete = respx.delete(f"{BASE}/conversations/c-1").respond(204)

        renamed = api_client.rename_conversation("c-1", "New", token="t")
        api_client.delete_conversation("c-1", token="t")

        self.assertEqual(sent(rename), {"title": "New"})
        self.assertEqual(renamed.title, "New")
        self.assertTrue(delete.called)

    @respx.mock
    def test_401_means_the_session_expired(self):
        respx.get(f"{BASE}/conversations").respond(401, json={"detail": "x"})

        with self.assertRaises(AuthExpired):
            api_client.list_conversations()


class TestAccounts(unittest.TestCase):
    @respx.mock
    def test_get_me(self):
        respx.get(f"{BASE}/auth/me").respond(json=USER)

        self.assertEqual(api_client.get_me("t").role, "user")

    @respx.mock
    def test_list_and_create_users(self):
        respx.get(f"{BASE}/admin/users").respond(json=[USER])
        create = respx.post(f"{BASE}/admin/users").respond(201, json=USER)

        users = api_client.list_users(token="t")
        created = api_client.create_user("ana@example.com", "temporary pass 123", "user", token="t")

        self.assertEqual([u.email for u in users], ["ana@example.com"])
        self.assertEqual(
            sent(create),
            {
                "email": "ana@example.com",
                "temporary_password": "temporary pass 123",
                "role": "user",
            },
        )
        self.assertEqual(created.id, "u-1")

    @respx.mock
    def test_update_sends_only_given_fields(self):
        route = respx.patch(f"{BASE}/admin/users/u-1").respond(json=USER)

        api_client.update_user("u-1", is_active=False)
        self.assertEqual(sent(route), {"is_active": False})
        api_client.update_user("u-1", role="admin", is_active=True)
        self.assertEqual(sent(route), {"role": "admin", "is_active": True})

    @respx.mock
    def test_reset_password(self):
        route = respx.post(f"{BASE}/admin/users/u-1/reset-password").respond(json=USER)

        api_client.reset_password("u-1", "another temp pass", token="t")

        self.assertEqual(sent(route), {"temporary_password": "another temp pass"})

    @respx.mock
    def test_api_messages_are_passed_through(self):
        respx.post(f"{BASE}/admin/users").respond(
            409, json={"detail": "A user with this email already exists."}
        )

        with self.assertRaisesRegex(RuntimeError, "already exists"):
            api_client.create_user("a@b.co", "temporary pass 123", "user")


if __name__ == "__main__":
    unittest.main()
