"""Retrieval-augmented chat: grounded prompts, citations, history and scoping."""

import unittest
import uuid

from tests.rag_helpers import PENGUINS, VOLCANOES, RagTestCase

QUESTION = "where do penguins live"


class TestRagChat(RagTestCase):
    def rag_chat(self, user, message=QUESTION, **body):
        return self.chat(user, message, use_rag=True, **body)

    def test_retrieved_passages_are_put_in_front_of_the_question(self):
        self.upload(self.alice, "penguins.txt", PENGUINS)

        response = self.rag_chat(self.alice)

        self.assertEqual(response.status_code, 200, response.text)
        _, messages = self.provider.calls[-1]
        prompt = messages[-1].content
        self.assertIn("Excerpts:", prompt)
        self.assertIn("[1] (penguins.txt)", prompt)
        self.assertIn("Penguins live in Antarctica", prompt)
        self.assertTrue(prompt.endswith(f"Question: {QUESTION}"))

    def test_the_stored_user_message_is_the_original_question(self):
        self.upload(self.alice, "penguins.txt", PENGUINS)
        body = self.rag_chat(self.alice).json()

        detail = self.client.get(
            f"/conversations/{body['conversation_id']}", headers=self.as_user(self.alice)
        ).json()

        self.assertEqual(detail["messages"][0]["content"], QUESTION)

    def test_answer_carries_citations_with_the_index_that_produced_them(self):
        self.upload(self.alice, "penguins.txt", PENGUINS)

        body = self.rag_chat(self.alice).json()

        self.assertTrue(body["citations"])
        first = body["citations"][0]
        self.assertEqual(first["filename"], "penguins.txt")
        self.assertEqual((first["embedding_name"], first["chunking_name"]), ("fake-a", "small"))
        self.assertGreater(first["score"], 0)

    def test_citations_are_stored_and_returned_with_the_history(self):
        self.upload(self.alice, "penguins.txt", PENGUINS)
        body = self.rag_chat(self.alice).json()

        detail = self.client.get(
            f"/conversations/{body['conversation_id']}", headers=self.as_user(self.alice)
        ).json()

        user_message, reply = detail["messages"]
        self.assertEqual(user_message["citations"], [])
        self.assertEqual(
            [c["chunk_id"] for c in reply["citations"]], [c["chunk_id"] for c in body["citations"]]
        )
        self.assertEqual(reply["retrieved_chunk_ids"], [c["chunk_id"] for c in body["citations"]])
        self.assertIsNone(reply["citations"][0]["score"])  # scores belong to the live search
        self.assertTrue(detail["use_rag"])

    def test_citations_disappear_from_history_when_access_is_lost(self):
        corpus = self.create_corpus("handbook")
        self.upload(self.admin, "shared.txt", PENGUINS, corpus_id=corpus["id"])
        self.client.post(
            f"/corpora/{corpus['id']}/access",
            json={"user_id": str(self.alice.id)},
            headers=self.as_user(self.admin),
        )
        body = self.rag_chat(self.alice).json()
        self.assertTrue(body["citations"])

        self.client.delete(
            f"/corpora/{corpus['id']}/access/{self.alice.id}", headers=self.as_user(self.admin)
        )
        detail = self.client.get(
            f"/conversations/{body['conversation_id']}", headers=self.as_user(self.alice)
        ).json()

        self.assertEqual(detail["messages"][1]["citations"], [])

    def test_unreadable_chunk_ids_in_history_are_ignored(self):
        from sqlalchemy.orm import Session

        from app.db.models import Message

        self.upload(self.alice, "penguins.txt", PENGUINS)
        body = self.rag_chat(self.alice).json()
        with Session(self.engine) as db:
            reply = db.get(Message, uuid.UUID(body["message_id"]))
            reply.retrieved_chunk_ids = ["not-a-uuid", *reply.retrieved_chunk_ids]
            db.commit()

        detail = self.client.get(
            f"/conversations/{body['conversation_id']}", headers=self.as_user(self.alice)
        ).json()

        self.assertEqual(len(detail["messages"][1]["citations"]), len(body["citations"]))

    def test_a_reply_with_only_unreadable_chunk_ids_has_no_citations(self):
        from sqlalchemy.orm import Session

        from app.db.models import Message

        body = self.chat(self.alice, "hi").json()
        with Session(self.engine) as db:
            db.get(Message, uuid.UUID(body["message_id"])).retrieved_chunk_ids = ["junk"]
            db.commit()

        detail = self.client.get(
            f"/conversations/{body['conversation_id']}", headers=self.as_user(self.alice)
        ).json()

        self.assertEqual(detail["messages"][1]["citations"], [])

    def test_without_the_flag_nothing_is_retrieved(self):
        self.upload(self.alice, "penguins.txt", PENGUINS)

        body = self.chat(self.alice, QUESTION).json()

        self.assertEqual(body["citations"], [])
        self.assertEqual(self.provider.calls[-1][1][-1].content, QUESTION)

    def test_no_matching_documents_means_a_plain_question(self):
        body = self.rag_chat(self.alice).json()

        self.assertEqual(body["citations"], [])
        self.assertEqual(self.provider.calls[-1][1][-1].content, QUESTION)

    def test_another_users_documents_are_never_used(self):
        self.upload(self.bob, "bob.txt", VOLCANOES)
        self.upload(self.alice, "alice.txt", PENGUINS)

        body = self.rag_chat(self.bob, "penguins Antarctica fish").json()

        self.assertEqual({c["filename"] for c in body["citations"]}, {"bob.txt"})
        self.assertNotIn("Penguins live", self.provider.calls[-1][1][-1].content)

    def test_embedding_and_chunking_choices_select_the_index(self):
        self.upload(self.alice, "a.txt", PENGUINS)
        self.upload(self.alice, "b.txt", PENGUINS, embedding="fake-b", chunking="para")

        body = self.rag_chat(self.alice, embedding="fake-b", chunking="para").json()

        self.assertEqual({c["filename"] for c in body["citations"]}, {"b.txt"})
        self.assertEqual(self.provider.embed_calls[-1][0], "fake-embed-b")

    def test_corpus_ids_narrow_the_shared_corpora(self):
        one = self.create_corpus("one", is_public=True)
        two = self.create_corpus("two", is_public=True)
        self.upload(self.admin, "one.txt", PENGUINS, corpus_id=one["id"])
        self.upload(self.admin, "two.txt", PENGUINS, corpus_id=two["id"])

        body = self.rag_chat(self.alice, corpus_ids=[two["id"]]).json()

        self.assertEqual({c["filename"] for c in body["citations"]}, {"two.txt"})
        detail = self.client.get(
            f"/conversations/{body['conversation_id']}", headers=self.as_user(self.alice)
        ).json()
        self.assertEqual(detail["corpus_ids"], [two["id"]])

    def test_a_chat_without_rag_after_a_rag_chat_clears_the_conversation_flag(self):
        self.upload(self.alice, "penguins.txt", PENGUINS)
        first = self.rag_chat(self.alice).json()

        self.chat(self.alice, "thanks", conversation_id=first["conversation_id"])

        detail = self.client.get(
            f"/conversations/{first['conversation_id']}", headers=self.as_user(self.alice)
        ).json()
        self.assertFalse(detail["use_rag"])

    def test_streaming_done_event_includes_citations(self):
        self.upload(self.alice, "penguins.txt", PENGUINS)

        response = self.rag_chat(self.alice, stream=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("event: done", response.text)
        self.assertIn('"citations"', response.text)
        self.assertIn("penguins.txt", response.text)

    def test_unknown_embedding_or_unavailable_provider_is_reported_before_the_model_runs(self):
        calls = len(self.provider.calls)

        unknown = self.rag_chat(self.alice, embedding="nope")
        offline = self.rag_chat(self.alice, embedding="offline")

        self.assertEqual((unknown.status_code, offline.status_code), (422, 503))
        self.assertEqual(len(self.provider.calls), calls)
        self.assertEqual(self.conversation_ids(self.alice), [])

    def test_embedding_failures_do_not_leak_provider_details(self):
        def fail(*args, **kwargs):
            raise RuntimeError("secret internal detail")

        self.provider.embed = fail

        response = self.rag_chat(self.alice)

        self.assertEqual(response.status_code, 502)
        self.assertNotIn("secret", response.text)


if __name__ == "__main__":
    unittest.main()
