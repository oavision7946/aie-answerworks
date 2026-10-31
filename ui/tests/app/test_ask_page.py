"""Drives the Ask view (question-answer) with streamlit's AppTest harness."""

import json
import unittest

import httpx
import respx

from app import config
from tests.app.helpers import ASK, ONE, RESULT, TWO, new_app

BASE = config.API_BASE_URL.rstrip("/")


class TestAskPage(unittest.TestCase):
    @respx.mock
    def test_initial_render_shows_hero_and_models(self):
        respx.get(f"{BASE}/models").respond(json=TWO)

        at = new_app(view=ASK).run()

        self.assertFalse(at.exception)
        self.assertEqual(at.selectbox[0].options, ["GPT-4o · openai", "Claude X · anthropic"])
        self.assertEqual(at.selectbox[0].value, "anthropic/claude-x")  # the API's default
        self.assertTrue(any("What would you like to know?" in m.value for m in at.markdown))
        self.assertEqual(len(at.chat_message), 0)

    @respx.mock
    def test_models_endpoint_down_falls_back_to_default_model(self):
        respx.get(f"{BASE}/models").mock(side_effect=httpx.ConnectError("down"))

        at = new_app(view=ASK).run()

        self.assertFalse(at.exception)
        self.assertEqual(at.selectbox[0].options, [config.FALLBACK_MODEL])
        self.assertEqual(at.selectbox[0].value, config.FALLBACK_MODEL)

    @respx.mock
    def test_unknown_default_selects_first_model(self):
        payload = {**TWO, "default_model": "ghost"}
        respx.get(f"{BASE}/models").respond(json=payload)

        at = new_app(view=ASK).run()

        self.assertEqual(at.selectbox[0].value, "openai/gpt-4o")

    @respx.mock
    def test_api_with_no_models_shows_warning_and_uses_fallback(self):
        respx.get(f"{BASE}/models").respond(json={"models": []})

        at = new_app(view=ASK).run()

        self.assertFalse(at.exception)
        self.assertEqual(len(at.sidebar.warning), 1)
        self.assertEqual(at.selectbox[0].value, config.FALLBACK_MODEL)

    @respx.mock
    def test_question_is_answered_with_metadata(self):
        respx.get(f"{BASE}/models").respond(json=TWO)
        ask = respx.post(f"{BASE}/ask").respond(json=RESULT)

        at = new_app(view=ASK).run()
        at.selectbox[0].select("openai/gpt-4o")
        at.chat_input[0].set_value("What is RAG?").run()

        self.assertFalse(at.exception)
        self.assertEqual(
            json.loads(ask.calls.last.request.content),
            {
                "question": "What is RAG?",
                "model": "gpt-4o",
                "provider": "openai",
                "force_bad_first_response": False,
            },
        )
        self.assertEqual([m.name for m in at.chat_message], ["user", "assistant"])
        rendered = " ".join(m.value for m in at.markdown)
        self.assertIn("What RAG is.", rendered)
        self.assertIn("1,234", rendered)
        self.assertIn("$0.000123", rendered)
        self.assertIn("openai / gpt-4o", rendered)
        self.assertEqual(len(at.session_state.messages), 2)
        # the hero is drawn before the question is handled; it is gone on the next rerun
        at.run()
        self.assertFalse(any("What would you like to know?" in m.value for m in at.markdown))

    @respx.mock
    def test_unpriced_model_shows_cost_as_not_available(self):
        respx.get(f"{BASE}/models").respond(json=ONE)
        respx.post(f"{BASE}/ask").respond(json={**RESULT, "cost_usd": None})

        at = new_app(view=ASK).run()
        at.chat_input[0].set_value("hi").run()

        self.assertIn("n/a", " ".join(m.value for m in at.markdown))

    @respx.mock
    def test_force_bad_first_response_checkbox_is_sent(self):
        respx.get(f"{BASE}/models").respond(json=ONE)
        ask = respx.post(f"{BASE}/ask").respond(json=RESULT)

        at = new_app(view=ASK).run()
        at.checkbox[1].check()  # [0] = stream, [1] = force bad first response
        at.chat_input[0].set_value("hi").run()

        self.assertTrue(json.loads(ask.calls.last.request.content)["force_bad_first_response"])

    @respx.mock
    def test_streaming_mode_uses_streaming_request(self):
        respx.get(f"{BASE}/models").respond(json=ONE)
        body = (
            'event: delta\ndata: {"content": "Streamed "}\n\n'
            'event: delta\ndata: {"content": "answer"}\n\n'
            f"event: done\ndata: {json.dumps({**RESULT, 'answer': 'Streamed answer'})}\n\n"
        )
        ask = respx.post(f"{BASE}/ask").respond(200, text=body)

        at = new_app(view=ASK).run()
        at.checkbox[0].check()
        at.chat_input[0].set_value("hi").run()

        self.assertFalse(at.exception)
        self.assertTrue(json.loads(ask.calls.last.request.content)["stream"])
        self.assertEqual(at.session_state.messages[-1]["content"], "Streamed answer")

    @respx.mock
    def test_api_error_is_shown_and_not_saved_as_answer(self):
        respx.get(f"{BASE}/models").respond(json=ONE)
        respx.post(f"{BASE}/ask").respond(502, json={"detail": "The AI service is down."})

        at = new_app(view=ASK).run()
        at.chat_input[0].set_value("hi").run()

        self.assertFalse(at.exception)
        self.assertEqual(len(at.error), 1)
        self.assertIn("The AI service is down.", at.error[0].value)
        self.assertEqual([m["role"] for m in at.session_state.messages], ["user"])

    @respx.mock
    def test_connection_failure_is_shown_as_error(self):
        respx.get(f"{BASE}/models").respond(json=ONE)
        respx.post(f"{BASE}/ask").mock(side_effect=httpx.ConnectError("refused"))

        at = new_app(view=ASK).run()
        at.chat_input[0].set_value("hi").run()

        self.assertFalse(at.exception)
        self.assertEqual(len(at.error), 1)

    @respx.mock
    def test_new_chat_clears_history(self):
        respx.get(f"{BASE}/models").respond(json=ONE)
        respx.post(f"{BASE}/ask").respond(json=RESULT)

        at = new_app(view=ASK).run()
        at.chat_input[0].set_value("hi").run()
        self.assertEqual(len(at.session_state.messages), 2)
        at.button[0].click().run()

        self.assertEqual(at.session_state.messages, [])
        self.assertEqual(len(at.chat_message), 0)


if __name__ == "__main__":
    unittest.main()
