"""End-to-end flow against running services: sign in, upload, ask with documents, history persists.

Needs the API (and optionally the UI) running with the keyless config in tests_e2e/config and an
admin account created. `make test-e2e` runs it; docs/testing.md shows how to start the stack.

Environment (defaults match the commands in docs/testing.md):
    E2E_API_URL, E2E_UI_URL, E2E_ADMIN_EMAIL, E2E_ADMIN_PASSWORD
"""

import os
import unittest
import uuid

import httpx

API = os.environ.get("E2E_API_URL", "http://localhost:18000").rstrip("/")
UI = os.environ.get("E2E_UI_URL", "http://localhost:18501").rstrip("/")
ADMIN_EMAIL = os.environ.get("E2E_ADMIN_EMAIL", "e2e-admin@example.com")
ADMIN_PASSWORD = os.environ.get("E2E_ADMIN_PASSWORD", "e2e admin passphrase")

DOCUMENT = (
    "Penguins live in the Southern Hemisphere, mostly in Antarctica. They eat fish and krill.\n"
    "Volcanoes are different: they erupt molten lava from magma chambers beneath the crust.\n"
)


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def login(client: httpx.Client, email: str, password: str) -> str:
    response = client.post("/auth/login", json={"email": email, "password": password})
    response.raise_for_status()
    return str(response.json()["access_token"])


class TestFullFlow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = httpx.Client(base_url=API, timeout=30)
        try:
            cls.client.get("/health").raise_for_status()
        except httpx.HTTPError as exc:
            raise unittest.SkipTest(f"The API is not reachable at {API}: {exc}") from exc
        cls.addClassCleanup(cls.client.close)

    def test_sign_in_upload_ask_and_history_persists(self):
        # 1. Sign in as the admin.
        admin = bearer(login(self.client, ADMIN_EMAIL, ADMIN_PASSWORD))
        me = self.client.get("/auth/me", headers=admin).json()
        self.assertEqual(me["role"], "admin")

        # 2. A regular user, who must choose their own password first.
        email = f"e2e-{uuid.uuid4().hex[:8]}@example.com"
        temporary, chosen = "temporary passphrase 1", "chosen passphrase 22"
        created = self.client.post(
            "/admin/users", headers=admin, json={"email": email, "temporary_password": temporary}
        )
        self.assertEqual(created.status_code, 201, created.text)
        pending = bearer(login(self.client, email, temporary))
        self.assertEqual(self.client.get("/models", headers=pending).status_code, 403)
        changed = self.client.post(
            "/auth/change-password",
            headers=pending,
            json={"current_password": temporary, "new_password": chosen},
        )
        self.assertEqual(changed.status_code, 204, changed.text)
        user = bearer(login(self.client, email, chosen))

        # 3. Upload a document; it is indexed with the default embedding model and splitter.
        uploaded = self.client.post(
            "/documents", headers=user, files={"file": ("penguins.txt", DOCUMENT.encode())}
        )
        self.assertEqual(uploaded.status_code, 201, uploaded.text)
        document = uploaded.json()
        self.assertEqual(document["status"], "ready")
        index = document["indexes"][0]
        self.assertEqual(index["embedding_name"], "fake-small")
        self.assertGreater(index["chunk_count"], 0)

        # 4. Ask with documents on: the answer comes with the passages it used.
        question = "What do penguins eat?"
        answer = self.client.post(
            "/chat", headers=user, json={"message": question, "use_rag": True}
        ).json()
        self.assertTrue(answer["citations"])
        self.assertEqual(answer["citations"][0]["filename"], "penguins.txt")
        self.assertIn("krill", answer["citations"][0]["text"])
        conversation_id = answer["conversation_id"]

        # 5. The conversation, its sources and a follow-up are still there when read back.
        follow_up = self.client.post(
            "/chat",
            headers=user,
            json={"message": "And volcanoes?", "conversation_id": conversation_id},
        )
        self.assertEqual(follow_up.status_code, 200, follow_up.text)
        stored = self.client.get(f"/conversations/{conversation_id}", headers=user).json()
        self.assertEqual([m["role"] for m in stored["messages"]], ["user", "assistant"] * 2)
        self.assertEqual(stored["messages"][0]["content"], question)
        self.assertTrue(stored["messages"][1]["citations"])
        listed = self.client.get("/conversations", headers=user).json()
        self.assertIn(conversation_id, [c["id"] for c in listed])

        # 6. Another user cannot reach any of it.
        other = bearer(login(self.client, ADMIN_EMAIL, ADMIN_PASSWORD))
        self.assertEqual(
            self.client.get(f"/conversations/{conversation_id}", headers=other).status_code, 404
        )
        self.assertEqual(
            self.client.get(f"/documents/{document['id']}", headers=other).status_code, 404
        )

        # 7. Clean up what this run created.
        self.client.delete(f"/conversations/{conversation_id}", headers=user)
        self.client.delete(f"/documents/{document['id']}", headers=user)

    def test_web_app_is_serving(self):
        try:
            response = httpx.get(f"{UI}/_stcore/health", timeout=10)
        except httpx.HTTPError as exc:
            self.skipTest(f"The web app is not reachable at {UI}: {exc}")
        self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
