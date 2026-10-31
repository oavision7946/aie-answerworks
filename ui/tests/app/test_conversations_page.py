"""Conversations page: list, open, rename, delete."""

import json
import unittest

import respx

from app import config
from tests.app.helpers import ONE, new_app

BASE = config.API_BASE_URL.rstrip("/")
CONV = "00000000-0000-0000-0000-00000000000a"
OTHER = "00000000-0000-0000-0000-00000000000b"
PAGE = "views/conversations.py"


def summary(conv_id=CONV, title="Budget plan", model="priced"):
    return {
        "id": conv_id,
        "title": title,
        "provider": "fake",
        "model": model,
        "updated_at": "2026-10-30T12:34:56Z",
    }


DETAIL = {
    **summary(),
    "messages": [
        {"id": "m1", "role": "user", "content": "hello", "model": None},
        {
            "id": "m2",
            "role": "assistant",
            "content": "Echo: hello",
            "provider": "fake",
            "model": "priced",
            "tokens_used": 4,
            "cost_usd": 0.5,
        },
    ],
}


def open_page(**kwargs):
    at = new_app(**kwargs).run()
    at.switch_page(PAGE).run()
    return at


def button(at, label, key_prefix=None):
    return next(b for b in at.button if b.label == label)


class TestConversationsPage(unittest.TestCase):
    def setUp(self):
        mock = respx.mock(assert_all_called=False)
        mock.start()
        self.addCleanup(mock.stop)
        mock.get(f"{BASE}/models").respond(json=ONE)
        self.list = mock.get(f"{BASE}/conversations").respond(
            json=[summary(), summary(OTHER, "Trip")]
        )
        self.mock = mock

    def test_lists_conversations_with_model_and_time(self):
        at = open_page()

        self.assertFalse(at.exception)
        text = " ".join(m.value for m in at.markdown)
        self.assertIn("Budget plan", text)
        self.assertIn("Trip", text)
        captions = " ".join(c.value for c in at.caption)
        self.assertIn("fake / priced", captions)
        self.assertIn("2026-10-30 12:34", captions)
        self.assertEqual(self.list.calls.last.request.headers["authorization"], "Bearer access-1")

    def test_empty_state(self):
        self.list.respond(json=[])

        at = open_page()

        self.assertIn("No saved conversations", at.info[0].value)

    def test_conversation_without_a_model_says_default(self):
        self.list.respond(json=[{**summary(), "provider": None, "model": None}])

        at = open_page()

        self.assertIn("default model", " ".join(c.value for c in at.caption))

    def test_open_loads_the_history_into_the_chat_page(self):
        self.mock.get(f"{BASE}/conversations/{CONV}").respond(json=DETAIL)

        at = open_page()
        at.button(key=f"open-{CONV}").click().run()

        self.assertFalse(at.exception)
        self.assertEqual(at.session_state.chat["conversation_id"], CONV)
        self.assertEqual([m.name for m in at.chat_message], ["user", "assistant"])
        text = " ".join(m.value for m in at.markdown)
        self.assertIn("Echo: hello", text)
        self.assertIn("fake / priced", text)  # usage line of the stored reply
        self.assertIn("Conversation: Budget plan", " ".join(c.value for c in at.caption))

    def test_rename_sends_the_new_title(self):
        rename = self.mock.patch(f"{BASE}/conversations/{CONV}").respond(json=summary(title="New"))

        at = open_page()
        at.text_input(key=f"title-{CONV}").set_value("  New  ")
        at.button(key=f"save-{CONV}").click().run()

        self.assertFalse(at.exception)
        self.assertEqual(json.loads(rename.calls.last.request.content), {"title": "  New  "})

    def test_rename_error_is_shown(self):
        self.mock.patch(f"{BASE}/conversations/{CONV}").respond(
            422, json={"detail": "Invalid request."}
        )

        at = open_page()
        at.text_input(key=f"title-{CONV}").set_value(" ")
        at.button(key=f"save-{CONV}").click().run()

        self.assertEqual(at.error[0].value, "Invalid request.")

    def test_delete_asks_for_confirmation_first(self):
        delete = self.mock.delete(f"{BASE}/conversations/{CONV}").respond(204)

        at = open_page()
        at.button(key=f"delete-{CONV}").click().run()

        self.assertIn("Delete this conversation", at.warning[0].value)
        self.assertFalse(delete.called)

    def test_confirmed_delete_calls_the_api_and_shows_a_notice(self):
        delete = self.mock.delete(f"{BASE}/conversations/{CONV}").respond(204)

        at = open_page()
        at.button(key=f"delete-{CONV}").click().run()
        at.button(key=f"yes-{CONV}").click().run()

        self.assertTrue(delete.called)
        self.assertIn("Deleted “Budget plan”", at.success[0].value)
        self.assertNotIn("confirm_delete", at.session_state)

    def test_cancel_keeps_the_conversation(self):
        delete = self.mock.delete(f"{BASE}/conversations/{CONV}").respond(204)

        at = open_page()
        at.button(key=f"delete-{CONV}").click().run()
        at.button(key=f"no-{CONV}").click().run()

        self.assertFalse(delete.called)
        self.assertEqual(len(at.warning), 0)

    def test_deleting_the_open_conversation_clears_the_chat(self):
        self.mock.delete(f"{BASE}/conversations/{CONV}").respond(204)
        at = new_app()
        at.session_state["chat"] = {
            "conversation_id": CONV,
            "title": "Budget plan",
            "messages": [{"role": "user", "content": "x", "response": None}],
        }
        at.run()
        at.switch_page(PAGE).run()

        at.button(key=f"delete-{CONV}").click().run()
        at.button(key=f"yes-{CONV}").click().run()

        self.assertIsNone(at.session_state.chat["conversation_id"])
        self.assertEqual(at.session_state.chat["messages"], [])

    def test_delete_error_is_shown(self):
        self.mock.delete(f"{BASE}/conversations/{CONV}").respond(
            404, json={"detail": "Conversation not found."}
        )

        at = open_page()
        at.button(key=f"delete-{CONV}").click().run()
        at.button(key=f"yes-{CONV}").click().run()

        self.assertEqual(at.error[0].value, "Conversation not found.")


if __name__ == "__main__":
    unittest.main()
