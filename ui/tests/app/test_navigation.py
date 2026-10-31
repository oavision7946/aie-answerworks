"""The app shell: who sees which pages, the account block, and role detection at sign-in."""

import unittest
from unittest.mock import patch

import httpx
import respx

from app import config
from tests.app.helpers import ADMIN_SIGNED_IN, ME_ADMIN, ME_USER, ONE, RAG_OPTIONS, new_app
from tests.app.test_auth_flow import PAIR, fill

BASE = config.API_BASE_URL.rstrip("/")
ADMIN_PAGE = "views/admin_users.py"


class TestPages(unittest.TestCase):
    @respx.mock
    def test_signed_in_users_land_on_chat(self):
        respx.get(f"{BASE}/rag/options").respond(json=RAG_OPTIONS)
        respx.get(f"{BASE}/models").respond(json=ONE)

        at = new_app().run()

        self.assertFalse(at.exception)
        self.assertEqual(len(at.chat_input), 1)
        self.assertEqual(at.chat_input[0].placeholder, "Message...")

    @respx.mock
    def test_regular_users_can_reach_ask_and_conversations(self):
        respx.get(f"{BASE}/rag/options").respond(json=RAG_OPTIONS)
        respx.get(f"{BASE}/models").respond(json=ONE)
        respx.get(f"{BASE}/conversations").respond(json=[])

        at = new_app().run()
        at.switch_page("views/ask.py").run()
        self.assertEqual(at.chat_input[0].placeholder, "Ask a question...")
        at.switch_page("views/conversations.py").run()

        self.assertFalse(at.exception)
        self.assertIn("No saved conversations", at.info[0].value)

    @respx.mock
    def test_the_admin_page_does_not_exist_for_regular_users(self):
        respx.get(f"{BASE}/rag/options").respond(json=RAG_OPTIONS)
        respx.get(f"{BASE}/models").respond(json=ONE)

        at = new_app().run()

        with self.assertRaises(ValueError):
            at.switch_page(ADMIN_PAGE)
        with self.assertRaises(ValueError):
            at.switch_page("views/admin_corpora.py")

    @respx.mock
    def test_regular_users_can_reach_documents(self):
        respx.get(f"{BASE}/rag/options").respond(json=RAG_OPTIONS)
        respx.get(f"{BASE}/models").respond(json=ONE)
        respx.get(f"{BASE}/documents").respond(json=[])
        respx.get(f"{BASE}/corpora").respond(json=[])

        at = new_app().run()
        at.switch_page("views/documents.py").run()

        self.assertFalse(at.exception)
        self.assertIn("You have not uploaded anything yet.", [i.value for i in at.info])

    @respx.mock
    def test_the_corpora_page_exists_for_admins(self):
        respx.get(f"{BASE}/rag/options").respond(json=RAG_OPTIONS)
        respx.get(f"{BASE}/models").respond(json=ONE)
        respx.get(f"{BASE}/corpora").respond(json=[])
        respx.get(f"{BASE}/admin/users").respond(json=[ME_ADMIN])

        at = new_app(auth=ADMIN_SIGNED_IN).run()
        at.switch_page("views/admin_corpora.py").run()

        self.assertFalse(at.exception)
        self.assertIn("## Corpora", [m.value for m in at.markdown])

    @respx.mock
    def test_the_admin_page_exists_for_admins(self):
        respx.get(f"{BASE}/rag/options").respond(json=RAG_OPTIONS)
        respx.get(f"{BASE}/models").respond(json=ONE)
        respx.get(f"{BASE}/admin/users").respond(json=[ME_ADMIN])

        at = new_app(auth=ADMIN_SIGNED_IN).run()
        at.switch_page(ADMIN_PAGE).run()

        self.assertFalse(at.exception)
        self.assertEqual(len(at.dataframe), 1)

    @respx.mock
    def test_anonymous_visitors_see_only_the_login_form_even_on_a_page_url(self):
        calls = respx.route().respond(500)

        at = new_app(auth=None).run()
        for page in (
            "views/chat.py",
            "views/ask.py",
            "views/documents.py",
            ADMIN_PAGE,
            "views/admin_corpora.py",
        ):
            with self.subTest(page=page):
                at.switch_page(page).run()
                self.assertFalse(at.exception)
                self.assertEqual(len(at.chat_input), 0)
                self.assertEqual(len(at.dataframe), 0)
                self.assertEqual([t.label for t in at.text_input], ["Email", "Password"])

        self.assertFalse(calls.called)


class TestAccountBlock(unittest.TestCase):
    @respx.mock
    def test_shows_who_is_signed_in_and_the_api_url(self):
        respx.get(f"{BASE}/rag/options").respond(json=RAG_OPTIONS)
        respx.get(f"{BASE}/models").respond(json=ONE)

        at = new_app().run()

        captions = [c.value for c in at.sidebar.caption]
        self.assertIn("Signed in as ana@example.com", captions)
        self.assertIn(f"API: {config.API_BASE_URL}", captions)

    @respx.mock
    def test_marks_admins(self):
        respx.get(f"{BASE}/rag/options").respond(json=RAG_OPTIONS)
        respx.get(f"{BASE}/models").respond(json=ONE)

        at = new_app(auth=ADMIN_SIGNED_IN).run()

        self.assertIn(
            "Signed in as root@example.com (admin)", [c.value for c in at.sidebar.caption]
        )

    def test_displays_a_custom_api_url(self):
        with patch.object(config, "API_BASE_URL", "http://example.test:9"):
            with respx.mock:
                respx.get("http://example.test:9/models").respond(json=ONE)
                at = new_app().run()

        self.assertIn("API: http://example.test:9", [c.value for c in at.sidebar.caption])


class TestRoleAtSignIn(unittest.TestCase):
    def sign_in(self):
        at = new_app(auth=None).run()
        fill(at, Email="x@example.com", Password="pw")
        at.button[0].click().run()
        return at

    @respx.mock
    def test_admin_role_is_read_from_the_api_and_unlocks_the_admin_page(self):
        respx.post(f"{BASE}/auth/login").respond(json=PAIR)
        respx.get(f"{BASE}/auth/me").respond(json=ME_ADMIN)
        respx.get(f"{BASE}/rag/options").respond(json=RAG_OPTIONS)
        respx.get(f"{BASE}/models").respond(json=ONE)
        respx.get(f"{BASE}/admin/users").respond(json=[ME_ADMIN])

        at = self.sign_in()

        self.assertEqual(at.session_state.auth["role"], "admin")
        at.switch_page(ADMIN_PAGE).run()
        self.assertFalse(at.exception)

    @respx.mock
    def test_regular_role_has_no_admin_page(self):
        respx.post(f"{BASE}/auth/login").respond(json=PAIR)
        respx.get(f"{BASE}/auth/me").respond(json=ME_USER)
        respx.get(f"{BASE}/rag/options").respond(json=RAG_OPTIONS)
        respx.get(f"{BASE}/models").respond(json=ONE)

        at = self.sign_in()

        self.assertEqual(at.session_state.auth["role"], "user")
        with self.assertRaises(ValueError):
            at.switch_page(ADMIN_PAGE)

    @respx.mock
    def test_if_the_role_cannot_be_read_the_user_is_treated_as_regular(self):
        respx.post(f"{BASE}/auth/login").respond(json=PAIR)
        respx.get(f"{BASE}/auth/me").mock(side_effect=httpx.ConnectError("down"))
        respx.get(f"{BASE}/rag/options").respond(json=RAG_OPTIONS)
        respx.get(f"{BASE}/models").respond(json=ONE)

        at = self.sign_in()

        self.assertEqual(at.session_state.auth["role"], "user")
        self.assertEqual(len(at.chat_input), 1)

    @respx.mock
    def test_token_refresh_keeps_the_role(self):
        respx.get(f"{BASE}/rag/options").respond(json=RAG_OPTIONS)
        respx.get(f"{BASE}/models").mock(
            side_effect=[httpx.Response(401, json={"detail": "x"}), httpx.Response(200, json=ONE)]
        )
        respx.post(f"{BASE}/auth/refresh").respond(json=PAIR)

        at = new_app(auth=ADMIN_SIGNED_IN).run()

        self.assertEqual(at.session_state.auth["role"], "admin")


if __name__ == "__main__":
    unittest.main()
