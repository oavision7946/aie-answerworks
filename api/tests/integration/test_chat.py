import uuid
from unittest.mock import patch

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Conversation, Message
from app.main import app
from app.services.llm.errors import FAILED, UNAVAILABLE, UNUSABLE, TransientProviderError
from app.services.llm.registry import ProviderRegistry, get_registry
from tests.chat_helpers import ChatTestCase
from tests.helpers import REQUEST, completion, fake_provider, make_registry, sse_frames

NO_RETRY_DELAY = patch("app.services.llm.retry.time.sleep")


class ChatCase(ChatTestCase):
    def setUp(self):
        super().setUp()
        patcher = NO_RETRY_DELAY
        patcher.start()
        self.addCleanup(patcher.stop)

    def detail(self, cid, user=None):
        return self.client.get(
            f"/conversations/{cid}", headers=self.as_user(user or self.alice)
        ).json()

    def stored_messages(self) -> list[Message]:
        with Session(self.engine) as db:
            return list(db.scalars(select(Message)))

    def stored_conversations(self) -> list[Conversation]:
        with Session(self.engine) as db:
            return list(db.scalars(select(Conversation)))


class TestChat(ChatCase):
    def test_first_message_starts_a_conversation(self):
        response = self.chat(self.alice, "What is pgvector?")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["answer"], "Echo: What is pgvector?")
        self.assertEqual((body["provider"], body["model"]), ("fake", "priced"))
        self.assertEqual(body["tokens_used"], 3 + 4)  # fake usage counts words in and out
        self.assertIsNotNone(body["cost_usd"])
        self.assertGreaterEqual(body["latency_ms"], 0)
        stored = self.detail(body["conversation_id"])
        self.assertEqual(stored["title"], "What is pgvector?")
        self.assertEqual((stored["provider"], stored["model"]), ("fake", "priced"))
        self.assertEqual([m["role"] for m in stored["messages"]], ["user", "assistant"])
        assistant = stored["messages"][1]
        self.assertEqual(assistant["id"], body["message_id"])
        self.assertEqual(assistant["tokens_used"], body["tokens_used"])
        self.assertEqual(assistant["cost_usd"], body["cost_usd"])
        self.assertEqual(assistant["retrieved_chunk_ids"], [])
        self.assertIsNone(stored["messages"][0]["tokens_used"])

    def test_long_first_messages_make_short_single_line_titles(self):
        cid = self.chat(self.alice, "word " * 50 + "\nend").json()["conversation_id"]

        title = self.detail(cid)["title"]

        self.assertLessEqual(len(title), 60)
        self.assertTrue(title.endswith("…"))
        self.assertNotIn("\n", title)

    def test_follow_up_sends_the_stored_history_to_the_model(self):
        cid = self.chat(self.alice, "my name is Ana").json()["conversation_id"]
        self.provider.script("Nice to meet you")
        self.chat(self.alice, "remember me?", conversation_id=cid)
        self.provider.calls.clear()

        self.chat(self.alice, "and now?", conversation_id=cid)

        _, prompt = self.provider.calls[-1]
        self.assertEqual(
            [(m.role, m.content) for m in prompt],
            [
                ("user", "my name is Ana"),
                ("assistant", "Echo: my name is Ana"),
                ("user", "remember me?"),
                ("assistant", "Nice to meet you"),
                ("user", "and now?"),
            ],
        )

    def test_history_is_limited_to_the_configured_number_of_messages(self):
        self.settings.app.chat.history_messages = 2
        cid = self.chat(self.alice, "one").json()["conversation_id"]
        self.chat(self.alice, "two", conversation_id=cid)
        self.provider.calls.clear()

        self.chat(self.alice, "three", conversation_id=cid)

        _, prompt = self.provider.calls[-1]
        self.assertEqual([m.content for m in prompt], ["two", "Echo: two", "three"])

    def test_each_reply_records_its_own_model_and_the_conversation_remembers_the_last(self):
        cid = self.chat(self.alice, "a", model="free").json()["conversation_id"]
        self.chat(self.alice, "b", conversation_id=cid, model="priced")
        self.chat(self.alice, "c", conversation_id=cid)  # no model: reuse the last one

        messages = self.detail(cid)["messages"]

        replies = [m for m in messages if m["role"] == "assistant"]
        self.assertEqual([m["model"] for m in replies], ["free", "priced", "priced"])
        self.assertIsNone(replies[0]["cost_usd"])  # "free" has no pricing configured
        self.assertIsNotNone(replies[1]["cost_usd"])
        self.assertEqual(self.detail(cid)["model"], "priced")

    def test_conversation_created_with_a_model_keeps_it_for_chat(self):
        created = self.client.post(
            "/conversations", json={"model": "free"}, headers=self.as_user(self.alice)
        ).json()

        body = self.chat(self.alice, "hi", conversation_id=created["id"]).json()

        self.assertEqual(body["model"], "free")

    def test_a_model_removed_from_config_falls_back_to_the_default(self):
        cid = self.chat(self.alice, "a").json()["conversation_id"]
        with Session(self.engine) as db:
            conversation = db.get(Conversation, uuid.UUID(cid))
            conversation.model = "retired-model"
            db.commit()

        body = self.chat(self.alice, "b", conversation_id=cid).json()

        self.assertEqual(body["model"], "priced")

    def test_an_explicit_choice_beats_the_stored_one(self):
        other = fake_provider("other")
        app.dependency_overrides[get_registry] = lambda: make_registry(self.provider, other)
        cid = self.chat(self.alice, "a").json()["conversation_id"]

        body = self.chat(self.alice, "b", conversation_id=cid, provider="other").json()

        self.assertEqual(body["provider"], "other")

    def test_unknown_model_or_conversation_is_rejected_before_calling_the_model(self):
        self.assertEqual(self.chat(self.alice, "x", model="nope").status_code, 422)
        self.assertEqual(
            self.chat(self.alice, "x", conversation_id=str(uuid.uuid4())).status_code, 404
        )
        self.assertEqual(self.provider.calls, [])
        self.assertEqual(self.stored_conversations(), [])

    def test_request_validation(self):
        self.assertEqual(self.chat(self.alice, "   ").status_code, 422)
        self.assertEqual(self.chat(self.alice, "").status_code, 422)
        self.assertEqual(self.chat(self.alice, "x" * 20001).status_code, 422)
        self.assertEqual(self.chat(self.alice, "x", conversation_id="not-a-uuid").status_code, 422)
        self.assertEqual(self.chat(self.alice, "x", surprise=1).status_code, 422)

    def test_messages_are_trimmed(self):
        cid = self.chat(self.alice, "  padded  ").json()["conversation_id"]

        self.assertEqual(self.detail(cid)["messages"][0]["content"], "padded")

    def test_no_providers_configured_is_503(self):
        app.dependency_overrides[get_registry] = lambda: ProviderRegistry({}, "", REQUEST)

        self.assertEqual(self.chat(self.alice, "x").status_code, 503)

    def test_no_providers_with_a_stored_model_is_still_503(self):
        cid = self.chat(self.alice, "a").json()["conversation_id"]
        app.dependency_overrides[get_registry] = lambda: ProviderRegistry({}, "", REQUEST)

        self.assertEqual(self.chat(self.alice, "b", conversation_id=cid).status_code, 503)


class TestChatFailures(ChatCase):
    def test_a_provider_outage_stores_nothing(self):
        self.provider.script(*[TransientProviderError("boom")] * 3)

        response = self.chat(self.alice, "hello")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"], UNAVAILABLE)
        self.assertEqual(self.stored_conversations(), [])
        self.assertEqual(self.stored_messages(), [])

    def test_a_failed_follow_up_leaves_the_conversation_unchanged(self):
        cid = self.chat(self.alice, "a").json()["conversation_id"]
        self.provider.script(RuntimeError("secret internals"))

        response = self.chat(self.alice, "b", conversation_id=cid)

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["detail"], FAILED)
        self.assertNotIn("secret", response.text)
        self.assertEqual(len(self.detail(cid)["messages"]), 2)

    def test_a_blank_answer_is_retried_once_then_rejected(self):
        self.provider.script("  ", completion(" "))

        response = self.chat(self.alice, "hello")

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["detail"], UNUSABLE)
        self.assertEqual(self.stored_messages(), [])

    def test_a_blank_answer_followed_by_a_good_one_is_stored_once(self):
        self.provider.script("", "second try")

        body = self.chat(self.alice, "hello").json()

        self.assertEqual(body["answer"], "second try")
        self.assertEqual(len(self.stored_messages()), 2)

    def test_deleting_the_conversation_during_the_call_is_a_404(self):
        cid = self.chat(self.alice, "a").json()["conversation_id"]
        original = self.provider.complete

        def delete_then_answer(model, messages):
            self.client.delete(f"/conversations/{cid}", headers=self.as_user(self.alice))
            return original(model, messages)

        self.provider.complete = delete_then_answer

        response = self.chat(self.alice, "b", conversation_id=cid)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.stored_messages(), [])


class TestChatStreaming(ChatCase):
    def stream(self, user, message="hello", **body):
        response = self.chat(user, message, stream=True, **body)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.headers["content-type"].startswith("text/event-stream"))
        return sse_frames(response.text)

    def test_streams_deltas_then_a_done_event_with_the_stored_ids(self):
        self.provider.script("one two three")

        frames = self.stream(self.alice, "count")

        self.assertEqual(
            [data["content"] for event, data in frames if event == "delta"],
            ["one ", "two ", "three"],
        )
        event, done = frames[-1]
        self.assertEqual(event, "done")
        self.assertEqual(done["answer"], "one two three")
        stored = self.detail(done["conversation_id"])
        self.assertEqual(stored["title"], "count")
        self.assertEqual(stored["messages"][1]["id"], done["message_id"])
        self.assertEqual(stored["messages"][1]["content"], "one two three")

    def test_streaming_continues_an_existing_conversation_with_history(self):
        cid = self.chat(self.alice, "first").json()["conversation_id"]
        self.provider.calls.clear()

        frames = self.stream(self.alice, "second", conversation_id=cid)

        self.assertEqual(frames[-1][1]["conversation_id"], cid)
        _, prompt = self.provider.calls[-1]
        self.assertEqual([m.content for m in prompt], ["first", "Echo: first", "second"])
        self.assertEqual(len(self.detail(cid)["messages"]), 4)

    def test_a_streaming_failure_is_an_error_event_and_stores_nothing(self):
        self.provider.script(*[TransientProviderError("boom")] * 3)

        frames = self.stream(self.alice, "hello")

        self.assertEqual(frames, [("error", {"detail": UNAVAILABLE})])
        self.assertEqual(self.stored_messages(), [])
        self.assertEqual(self.stored_conversations(), [])

    def test_unknown_conversation_is_a_404_before_streaming_starts(self):
        response = self.chat(self.alice, "x", stream=True, conversation_id=str(uuid.uuid4()))

        self.assertEqual(response.status_code, 404)

    def test_other_users_conversation_is_a_404_when_streaming(self):
        cid = self.chat(self.alice, "private").json()["conversation_id"]

        response = self.chat(self.bob, "x", stream=True, conversation_id=cid)

        self.assertEqual(response.status_code, 404)

    def test_deleting_the_conversation_mid_stream_is_reported(self):
        cid = self.chat(self.alice, "a").json()["conversation_id"]
        original = self.provider.stream

        def delete_then_stream(model, messages):
            self.client.delete(f"/conversations/{cid}", headers=self.as_user(self.alice))
            yield from original(model, messages)

        self.provider.stream = delete_then_stream

        frames = self.stream(self.alice, "b", conversation_id=cid)

        self.assertEqual(frames[-1], ("error", {"detail": "Conversation not found."}))

    def test_a_storage_error_is_reported_without_details(self):
        with patch(
            "app.services.chat_service.conversation_repo.add_exchange",
            side_effect=RuntimeError("db password leaked"),
        ):
            frames = self.stream(self.alice, "hello")

        self.assertEqual(frames[-1], ("error", {"detail": FAILED}))
        self.assertNotIn("leaked", str(frames))
