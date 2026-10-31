"""Chat page with documents: the toggle, retrieval settings and cited sources."""

import json
import unittest

import respx

from app import config
from tests.app.helpers import CHAT, CHAT_RESULT, CORPUS, ONE, RAG_OPTIONS, new_app

BASE = config.API_BASE_URL.rstrip("/")
CITATION = {
    "chunk_id": "c-1",
    "document_id": "d-1",
    "filename": "notes.txt",
    "chunk_index": 0,
    "text": "Penguins live in Antarctica.",
    "score": 0.82,
    "embedding_name": "small",
    "chunking_name": "recursive",
}
GROUNDED = {**CHAT_RESULT, "citations": [CITATION, {**CITATION, "chunk_id": "c-2", "score": None}]}
SECOND = {**CORPUS, "id": "k-2", "name": "faq"}


def sent(route) -> dict:
    return json.loads(route.calls.last.request.content)


def toggle(at):
    return next(t for t in at.toggle if t.label == "Answer from my documents")


class TestChatWithDocuments(unittest.TestCase):
    def setUp(self):
        mock = respx.mock(assert_all_called=False)
        mock.start()
        self.addCleanup(mock.stop)
        mock.get(f"{BASE}/models").respond(json=ONE)
        self.options = mock.get(f"{BASE}/rag/options").respond(json=RAG_OPTIONS)
        self.corpora = mock.get(f"{BASE}/corpora").respond(json=[CORPUS, SECOND])
        self.chat = mock.post(f"{BASE}/chat").respond(json=GROUNDED)
        self.mock = mock

    def test_documents_are_off_by_default_and_nothing_extra_is_requested(self):
        at = new_app(view=CHAT).run()
        at.chat_input[0].set_value("hello").run()

        self.assertFalse(at.exception)
        self.assertFalse(toggle(at).value)
        self.assertNotIn("use_rag", sent(self.chat))
        self.assertFalse(self.corpora.called)

    def test_turning_it_on_requests_retrieval_with_the_defaults(self):
        at = new_app(view=CHAT).run()
        toggle(at).set_value(True).run()
        at.chat_input[0].set_value("where do penguins live").run()

        self.assertFalse(at.exception)
        body = sent(self.chat)
        self.assertTrue(body["use_rag"])
        self.assertEqual((body["embedding"], body["chunking"]), ("small", "recursive"))
        self.assertNotIn("corpus_ids", body)  # all readable corpora

    def test_the_embedding_model_and_splitter_can_be_chosen(self):
        at = new_app(view=CHAT).run()
        toggle(at).set_value(True).run()
        next(s for s in at.selectbox if s.key == "chat-embedding").select_index(1)
        next(s for s in at.selectbox if s.key == "chat-chunking").select_index(1)
        at.chat_input[0].set_value("q").run()

        body = sent(self.chat)
        self.assertEqual((body["embedding"], body["chunking"]), ("large", "sentence"))

    def test_corpora_can_be_narrowed(self):
        at = new_app(view=CHAT).run()
        toggle(at).set_value(True).run()
        picker = next(m for m in at.multiselect if m.label == "Shared corpora")
        self.assertEqual(picker.value, ["k-1", "k-2"])
        picker.set_value(["k-2"])
        at.chat_input[0].set_value("q").run()

        self.assertEqual(sent(self.chat)["corpus_ids"], ["k-2"])

    def test_deselecting_every_corpus_searches_only_my_documents(self):
        at = new_app(view=CHAT).run()
        toggle(at).set_value(True).run()
        next(m for m in at.multiselect if m.label == "Shared corpora").set_value([])
        at.chat_input[0].set_value("q").run()

        self.assertEqual(sent(self.chat)["corpus_ids"], [])

    def test_answers_show_their_sources(self):
        at = new_app(view=CHAT).run()
        toggle(at).set_value(True).run()
        at.chat_input[0].set_value("q").run()

        sources = next(e for e in at.expander if e.label == "Sources (2)")
        text = " ".join(m.value for m in sources.markdown)
        self.assertIn("[1] notes.txt", text)
        self.assertIn("similarity 0.82", text)
        self.assertNotIn("similarity None", text)
        captions = " ".join(c.value for c in sources.caption)
        self.assertIn("Penguins live in Antarctica.", captions)
        self.assertIn("indexed with small · recursive", captions)

    def test_answers_without_citations_have_no_sources_section(self):
        self.chat.respond(json=CHAT_RESULT)

        at = new_app(view=CHAT).run()
        at.chat_input[0].set_value("q").run()

        self.assertNotIn("Sources", " ".join(e.label for e in at.expander))

    def test_long_passages_are_shortened(self):
        long = {**CITATION, "text": "word " * 200}
        self.chat.respond(json={**CHAT_RESULT, "citations": [long]})

        at = new_app(view=CHAT).run()
        at.chat_input[0].set_value("q").run()

        sources = next(e for e in at.expander if e.label == "Sources (1)")
        self.assertTrue(any(c.value.endswith("…") for c in sources.caption))

    def test_retrieval_settings_are_hidden_when_documents_are_unavailable(self):
        self.options.respond(500, json={"detail": "boom"})

        at = new_app(view=CHAT).run()

        self.assertFalse(at.exception)
        self.assertEqual(len(at.toggle), 0)
        self.assertIn(
            "Documents are not available right now.", [c.value for c in at.sidebar.caption]
        )
        at.chat_input[0].set_value("hello").run()
        self.assertNotIn("use_rag", sent(self.chat))

    def test_no_corpora_means_no_corpus_picker(self):
        self.corpora.respond(json=[])

        at = new_app(view=CHAT).run()
        toggle(at).set_value(True).run()
        at.chat_input[0].set_value("q").run()

        self.assertEqual(len(at.multiselect), 0)
        self.assertNotIn("corpus_ids", sent(self.chat))

    def test_a_corpus_list_failure_does_not_block_chatting(self):
        self.corpora.respond(500, json={"detail": "boom"})

        at = new_app(view=CHAT).run()
        toggle(at).set_value(True).run()
        at.chat_input[0].set_value("q").run()

        self.assertFalse(at.exception)
        self.assertTrue(sent(self.chat)["use_rag"])

    def test_streaming_with_documents_shows_sources(self):
        done = json.dumps(GROUNDED)
        self.chat.respond(
            text=f'event: delta\ndata: {{"content": "Hi"}}\n\nevent: done\ndata: {done}\n\n',
            headers={"content-type": "text/event-stream"},
        )

        at = new_app(view=CHAT).run()
        toggle(at).set_value(True).run()
        next(c for c in at.sidebar.checkbox if c.label == "Stream responses").check().run()
        at.chat_input[0].set_value("q").run()

        self.assertFalse(at.exception)
        self.assertTrue(sent(self.chat)["use_rag"])
        self.assertIn("Sources (2)", [e.label for e in at.expander])

    def test_sources_stay_visible_for_earlier_messages(self):
        at = new_app(view=CHAT).run()
        toggle(at).set_value(True).run()
        at.chat_input[0].set_value("one").run()
        at.chat_input[0].set_value("two").run()

        self.assertEqual([e.label for e in at.expander].count("Sources (2)"), 2)

    def test_resumed_conversations_show_the_sources_of_their_answers(self):
        at = new_app(view=CHAT)
        at.session_state["chat"] = {
            "conversation_id": "c-1",
            "title": "T",
            "messages": [
                {"role": "user", "content": "q", "response": None},
                {
                    "role": "assistant",
                    "content": "a",
                    "response": {
                        "answer": "a",
                        "provider": "openai",
                        "model": "gpt-4o",
                        "tokens_used": 1,
                        "cost_usd": None,
                        "citations": [CITATION],
                    },
                },
            ],
        }
        at.run()

        self.assertIn("Sources (1)", [e.label for e in at.expander])

    def test_opening_a_saved_conversation_restores_its_sources(self):
        summary = {
            "id": "c-1",
            "title": "Penguins",
            "provider": "openai",
            "model": "gpt-4o",
            "updated_at": "2026-10-31T10:00:00Z",
        }
        detail = {
            **summary,
            "messages": [
                {"id": "m1", "role": "user", "content": "q"},
                {
                    "id": "m2",
                    "role": "assistant",
                    "content": "a",
                    "provider": "openai",
                    "model": "gpt-4o",
                    "tokens_used": 3,
                    "cost_usd": None,
                    "citations": [CITATION],
                },
            ],
        }
        self.mock.get(f"{BASE}/conversations").respond(json=[summary])
        self.mock.get(f"{BASE}/conversations/c-1").respond(json=detail)

        at = new_app().run()
        at.switch_page("views/conversations.py").run()
        next(b for b in at.button if b.label == "Open").click().run()

        self.assertFalse(at.exception)
        self.assertIn("Sources (1)", [e.label for e in at.expander])


if __name__ == "__main__":
    unittest.main()
