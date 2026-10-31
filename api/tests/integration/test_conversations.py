import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.db.models import Conversation
from tests.chat_helpers import ChatTestCase


class TestConversationEndpoints(ChatTestCase):
    def create(self, user=None, **body):
        return self.client.post(
            "/conversations", json=body, headers=self.as_user(user or self.alice)
        )

    def test_create_uses_a_default_title_and_no_model(self):
        response = self.create()

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["title"], "New conversation")
        self.assertIsNone(body["provider"])
        self.assertIsNone(body["model"])
        self.assertFalse(body["use_rag"])
        self.assertEqual(body["corpus_ids"], [])

    def test_create_with_title_and_model(self):
        body = self.create(title="  Budget  ", provider="fake", model="free").json()

        self.assertEqual(
            (body["title"], body["provider"], body["model"]), ("Budget", "fake", "free")
        )

    def test_create_rejects_an_unknown_model(self):
        self.assertEqual(self.create(provider="fake", model="nope").status_code, 422)

    def test_create_rejects_unknown_fields_and_blank_titles(self):
        self.assertEqual(self.create(owner="x").status_code, 422)
        self.assertEqual(self.create(title="   ").status_code, 422)

    def test_list_is_newest_activity_first_and_paginated(self):
        first = self.create(title="first").json()["id"]
        second = self.create(title="second").json()["id"]
        self.chat(self.alice, "ping", conversation_id=first)  # bumps "first" to the top

        self.assertEqual(self.conversation_ids(self.alice), [first, second])
        page = self.client.get(
            "/conversations?limit=1&offset=1", headers=self.as_user(self.alice)
        ).json()
        self.assertEqual([c["id"] for c in page], [second])
        too_big = self.client.get("/conversations?limit=500", headers=self.as_user(self.alice))
        self.assertEqual(too_big.status_code, 422)

    def test_get_returns_messages_in_order(self):
        cid = self.chat(self.alice, "one").json()["conversation_id"]
        self.chat(self.alice, "two", conversation_id=cid)

        body = self.client.get(f"/conversations/{cid}", headers=self.as_user(self.alice)).json()

        self.assertEqual(
            [(m["role"], m["content"]) for m in body["messages"]],
            [
                ("user", "one"),
                ("assistant", "Echo: one"),
                ("user", "two"),
                ("assistant", "Echo: two"),
            ],
        )

    def test_rename(self):
        cid = self.create().json()["id"]

        response = self.client.patch(
            f"/conversations/{cid}", json={"title": " Plans "}, headers=self.as_user(self.alice)
        )

        self.assertEqual(response.json()["title"], "Plans")
        blank = self.client.patch(
            f"/conversations/{cid}", json={"title": " "}, headers=self.as_user(self.alice)
        )
        self.assertEqual(blank.status_code, 422)

    def test_delete_removes_the_conversation_and_its_messages(self):
        cid = self.chat(self.alice, "hi").json()["conversation_id"]

        response = self.client.delete(f"/conversations/{cid}", headers=self.as_user(self.alice))

        self.assertEqual(response.status_code, 204)
        self.assertEqual(self.conversation_ids(self.alice), [])
        self.assertEqual(
            self.client.get(f"/conversations/{cid}", headers=self.as_user(self.alice)).status_code,
            404,
        )
        with self.engine.connect() as connection:
            count = connection.exec_driver_sql("SELECT COUNT(*) FROM messages").scalar()
        self.assertEqual(count, 0)

    def test_unknown_id_is_404_for_every_action(self):
        missing = uuid.uuid4()
        headers = self.as_user(self.alice)

        self.assertEqual(
            self.client.get(f"/conversations/{missing}", headers=headers).status_code, 404
        )
        self.assertEqual(
            self.client.patch(
                f"/conversations/{missing}", json={"title": "x"}, headers=headers
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.delete(f"/conversations/{missing}", headers=headers).status_code, 404
        )


class TestConversationIsolation(ChatTestCase):
    """User A can never see or change user B's conversations; they look like they do not exist."""

    def setUp(self):
        super().setUp()
        self.cid = self.chat(self.alice, "alice secret").json()["conversation_id"]

    def test_other_users_see_an_empty_list(self):
        self.assertEqual(self.conversation_ids(self.bob), [])

    def test_other_users_cannot_read_rename_or_delete(self):
        headers = self.as_user(self.bob)

        self.assertEqual(
            self.client.get(f"/conversations/{self.cid}", headers=headers).status_code, 404
        )
        self.assertEqual(
            self.client.patch(
                f"/conversations/{self.cid}", json={"title": "mine now"}, headers=headers
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.delete(f"/conversations/{self.cid}", headers=headers).status_code, 404
        )

        self.assertEqual(self.conversation_ids(self.alice), [self.cid])
        detail = self.client.get(f"/conversations/{self.cid}", headers=self.as_user(self.alice))
        self.assertNotEqual(detail.json()["title"], "mine now")

    def test_other_users_cannot_post_into_the_conversation(self):
        before = len(self.provider.calls)

        response = self.chat(self.bob, "intrude", conversation_id=self.cid)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(len(self.provider.calls), before)  # the model was never called
        detail = self.client.get(f"/conversations/{self.cid}", headers=self.as_user(self.alice))
        self.assertEqual(len(detail.json()["messages"]), 2)


class TestConversationAccessRules(ChatTestCase):
    def test_anonymous_requests_are_401(self):
        cid = str(uuid.uuid4())
        for method, path in [
            ("post", "/conversations"),
            ("get", "/conversations"),
            ("get", f"/conversations/{cid}"),
            ("patch", f"/conversations/{cid}"),
            ("delete", f"/conversations/{cid}"),
            ("post", "/chat"),
        ]:
            with self.subTest(method=method, path=path):
                self.assertEqual(getattr(self.client, method)(path).status_code, 401)

    def test_pending_password_change_blocks_conversations_and_chat(self):
        fresh = self.add_user("fresh@example.com", must_change_password=True)
        headers = self.as_user(fresh)

        self.assertEqual(self.client.get("/conversations", headers=headers).status_code, 403)
        self.assertEqual(self.chat(fresh).status_code, 403)

    def test_deactivated_users_are_locked_out_immediately(self):
        headers = self.as_user(self.alice)
        with Session(self.engine) as db:
            from app.db.repositories import user_repo

            user = user_repo.get_by_id(db, self.alice.id)
            user.is_active = False
            user_repo.save(db, user)

        self.assertEqual(self.client.get("/conversations", headers=headers).status_code, 403)


class TestConversationModel(ChatTestCase):
    def test_timestamps_and_defaults(self):
        with Session(self.engine) as db:
            conversation = Conversation(user_id=self.alice.id, title="t")
            db.add(conversation)
            db.commit()

            self.assertIsInstance(conversation.created_at, datetime)
            self.assertEqual(conversation.created_at.tzinfo or UTC, UTC)
            self.assertEqual(conversation.corpus_ids, [])
            self.assertFalse(conversation.use_rag)
