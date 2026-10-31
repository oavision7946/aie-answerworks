"""Chat page: stored conversations driven through POST /chat."""

import json
import unittest

import httpx
import respx

from app import config
from tests.app.helpers import CHAT, CHAT_RESULT, ONE, TWO, new_app

BASE = config.API_BASE_URL.rstrip("/")


def rendered(at):
    return " ".join(m.value for m in at.markdown)


class TestChatPage(unittest.TestCase):
    def setUp(self):
        mock = respx.mock(assert_all_called=False)
        mock.start()
        self.addCleanup(mock.stop)
        self.models = mock.get(f"{BASE}/models").respond(json=ONE)
        self.chat = mock.post(f"{BASE}/chat").respond(json=CHAT_RESULT)
        self.mock = mock

    def test_empty_chat_shows_the_welcome(self):
        at = new_app(view=CHAT).run()

        self.assertFalse(at.exception)
        self.assertIn("Your messages are saved", rendered(at))
        self.assertEqual(len(at.chat_message), 0)

    def test_first_message_starts_a_conversation_and_follow_up_continues_it(self):
        at = new_app(view=CHAT).run()
        at.chat_input[0].set_value("What is RAG?").run()

        self.assertFalse(at.exception)
        first = json.loads(self.chat.calls.last.request.content)
        self.assertEqual(
            first, {"message": "What is RAG?", "model": "gpt-4o-mini", "provider": "openai"}
        )
        self.assertEqual(self.chat.calls.last.request.headers["authorization"], "Bearer access-1")
        self.assertEqual(at.session_state.chat["conversation_id"], "c-1")
        self.assertEqual([m.name for m in at.chat_message], ["user", "assistant"])
        self.assertIn("1,234", rendered(at))

        at.chat_input[0].set_value("And more?").run()

        second = json.loads(self.chat.calls.last.request.content)
        self.assertEqual(second["conversation_id"], "c-1")
        self.assertEqual(len(at.session_state.chat["messages"]), 4)

    def test_streaming_uses_the_streaming_request(self):
        body = (
            'event: delta\ndata: {"content": "Streamed "}\n\n'
            'event: delta\ndata: {"content": "answer"}\n\n'
            f"event: done\ndata: {json.dumps({**CHAT_RESULT, 'answer': 'Streamed answer'})}\n\n"
        )
        self.chat.respond(200, text=body)

        at = new_app(view=CHAT).run()
        at.checkbox[0].check()
        at.chat_input[0].set_value("hi").run()

        self.assertFalse(at.exception)
        self.assertTrue(json.loads(self.chat.calls.last.request.content)["stream"])
        self.assertEqual(at.session_state.chat["messages"][-1]["content"], "Streamed answer")
        self.assertEqual(at.session_state.chat["conversation_id"], "c-1")

    def test_a_failed_message_is_reported_as_not_saved(self):
        self.chat.respond(502, json={"detail": "The AI service is down."})

        at = new_app(view=CHAT).run()
        at.chat_input[0].set_value("hi").run()

        self.assertFalse(at.exception)
        self.assertIn("The AI service is down.", at.error[0].value)
        self.assertIn("not saved", at.error[0].value)
        self.assertEqual(at.session_state.chat["messages"], [])
        self.assertIsNone(at.session_state.chat["conversation_id"])

    def test_connection_failure_is_shown(self):
        self.chat.mock(side_effect=httpx.ConnectError("refused"))

        at = new_app(view=CHAT).run()
        at.chat_input[0].set_value("hi").run()

        self.assertFalse(at.exception)
        self.assertEqual(len(at.error), 1)

    def test_new_chat_starts_over(self):
        at = new_app(view=CHAT).run()
        at.chat_input[0].set_value("hi").run()
        self.assertEqual(at.session_state.chat["conversation_id"], "c-1")

        next(b for b in at.sidebar.button if "New chat" in b.label).click().run()

        self.assertIsNone(at.session_state.chat["conversation_id"])
        self.assertEqual(len(at.chat_message), 0)

    def test_resumed_conversation_preselects_its_model(self):
        self.models.respond(json=TWO)
        at = new_app(view=CHAT)
        at.session_state["chat"] = {
            "conversation_id": "c-9",
            "title": "Old",
            "messages": [
                {"role": "user", "content": "q", "response": None},
                {
                    "role": "assistant",
                    "content": "a",
                    "response": {
                        "answer": "a",
                        "provider": "openai",
                        "model": "gpt-4o",
                        "tokens_used": 3,
                        "cost_usd": None,
                    },
                },
            ],
        }
        at.run()

        self.assertEqual(at.selectbox[0].value, "openai/gpt-4o")  # TWO's default is claude-x
        self.assertIn("Conversation: Old", " ".join(c.value for c in at.caption))

    def test_anonymous_session_renders_nothing(self):
        at = new_app(auth=None, view=CHAT).run()

        self.assertFalse(at.exception)
        self.assertEqual(len(at.chat_input), 0)
        self.assertFalse(self.models.called)


if __name__ == "__main__":
    unittest.main()
