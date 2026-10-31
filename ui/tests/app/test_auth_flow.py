"""Sign-in gate, forced password change, sign out and token refresh on the real page."""

import json
import unittest

import httpx
import respx

from app import config
from tests.app.helpers import CHAT_RESULT, ME_USER, ONE, SIGNED_IN, new_app

BASE = config.API_BASE_URL.rstrip("/")
PAIR = {"access_token": "access-2", "refresh_token": "refresh-2", "must_change_password": False}
NEW_PASSWORD = "a brand new passphrase"


def fill(at, **values):
    for label, value in values.items():
        next(t for t in at.text_input if t.label == label).set_value(value)
    return at


def texts(elements):
    return " ".join(e.value for e in elements)


class TestLogin(unittest.TestCase):
    @respx.mock
    def test_anonymous_visitor_sees_only_the_login_form(self):
        models = respx.get(f"{BASE}/models").respond(json=ONE)

        at = new_app(auth=None).run()

        self.assertFalse(at.exception)
        self.assertEqual([t.label for t in at.text_input], ["Email", "Password"])
        self.assertEqual(len(at.chat_input), 0)
        self.assertEqual(len(at.sidebar.selectbox), 0)
        self.assertFalse(models.called)

    @respx.mock
    def test_successful_login_shows_chat_and_sends_token(self):
        login = respx.post(f"{BASE}/auth/login").respond(json=PAIR)
        respx.get(f"{BASE}/auth/me").respond(json=ME_USER)
        models = respx.get(f"{BASE}/models").respond(json=ONE)

        at = new_app(auth=None).run()
        fill(at, Email=" Ana@Example.com ", Password="pw")
        at.button[0].click().run()

        self.assertFalse(at.exception)
        self.assertEqual(
            json.loads(login.calls.last.request.content),
            {"email": " Ana@Example.com ", "password": "pw"},
        )
        self.assertEqual(len(at.chat_input), 1)
        self.assertEqual(models.calls.last.request.headers["authorization"], "Bearer access-2")
        self.assertIn("Signed in as ana@example.com", texts(at.sidebar.caption))

    @respx.mock
    def test_wrong_credentials_show_the_api_message(self):
        respx.post(f"{BASE}/auth/login").respond(
            401, json={"detail": "Incorrect email or password."}
        )

        at = new_app(auth=None).run()
        fill(at, Email="ana@example.com", Password="nope")
        at.button[0].click().run()

        self.assertEqual(at.error[0].value, "Incorrect email or password.")
        self.assertEqual(len(at.chat_input), 0)

    @respx.mock
    def test_unreachable_api_shows_a_message(self):
        respx.post(f"{BASE}/auth/login").mock(side_effect=httpx.ConnectError("down"))

        at = new_app(auth=None).run()
        fill(at, Email="ana@example.com", Password="pw")
        at.button[0].click().run()

        self.assertIn("Could not reach the API", at.error[0].value)

    @respx.mock
    def test_empty_fields_are_not_submitted(self):
        login = respx.post(f"{BASE}/auth/login").respond(json=PAIR)

        at = new_app(auth=None).run()
        at.button[0].click().run()

        self.assertEqual(at.error[0].value, "Enter your email and password.")
        self.assertFalse(login.called)

    @respx.mock
    def test_unexpected_login_response(self):
        respx.post(f"{BASE}/auth/login").respond(json={"nope": 1})

        at = new_app(auth=None).run()
        fill(at, Email="ana@example.com", Password="pw")
        at.button[0].click().run()

        self.assertIn("unexpected response", at.error[0].value)


class TestSignOut(unittest.TestCase):
    @respx.mock
    def test_sign_out_clears_session_and_chat(self):
        respx.get(f"{BASE}/models").respond(json=ONE)
        respx.post(f"{BASE}/chat").respond(json=CHAT_RESULT)

        at = new_app().run()
        at.chat_input[0].set_value("hi").run()
        next(b for b in at.sidebar.button if b.label == "Sign out").click().run()

        self.assertEqual([t.label for t in at.text_input], ["Email", "Password"])
        self.assertNotIn("auth", at.session_state)
        self.assertEqual(at.session_state.messages, [])
        self.assertEqual(at.session_state.chat["messages"], [])
        self.assertIsNone(at.session_state.chat["conversation_id"])


class TestForcedPasswordChange(unittest.TestCase):
    PENDING = {**SIGNED_IN, "must_change_password": True}

    def submit(self, at, current="temp password!", new=NEW_PASSWORD, confirm=NEW_PASSWORD):
        fill(at, **{"Current password": current, "New password": new})
        fill(at, **{"Confirm new password": confirm})
        next(b for b in at.button if b.label == "Change password").click().run()

    @respx.mock
    def test_chat_is_blocked_until_password_is_changed(self):
        models = respx.get(f"{BASE}/models").respond(json=ONE)

        at = new_app(auth=self.PENDING).run()

        self.assertFalse(at.exception)
        self.assertEqual(len(at.chat_input), 0)
        self.assertIn("Choose a new password", texts(at.markdown))
        self.assertFalse(models.called)

    @respx.mock
    def test_successful_change_signs_in_with_new_password(self):
        change = respx.post(f"{BASE}/auth/change-password").respond(204)
        login = respx.post(f"{BASE}/auth/login").respond(json=PAIR)
        respx.get(f"{BASE}/auth/me").respond(json=ME_USER)
        respx.get(f"{BASE}/models").respond(json=ONE)

        at = new_app(auth=self.PENDING).run()
        self.submit(at)

        self.assertFalse(at.exception)
        self.assertEqual(change.calls.last.request.headers["authorization"], "Bearer access-1")
        self.assertEqual(
            json.loads(change.calls.last.request.content),
            {"current_password": "temp password!", "new_password": NEW_PASSWORD},
        )
        self.assertEqual(
            json.loads(login.calls.last.request.content),
            {"email": "ana@example.com", "password": NEW_PASSWORD},
        )
        self.assertEqual(len(at.chat_input), 1)

    @respx.mock
    def test_short_or_mismatched_password_is_rejected_locally(self):
        change = respx.post(f"{BASE}/auth/change-password").respond(204)

        at = new_app(auth=self.PENDING).run()
        self.submit(at, new="short", confirm="short")
        self.assertIn("at least 12", at.error[0].value)
        self.submit(at, confirm="something else entirely")
        self.assertIn("do not match", at.error[0].value)

        self.assertFalse(change.called)

    @respx.mock
    def test_api_rejection_is_shown(self):
        respx.post(f"{BASE}/auth/change-password").respond(
            400, json={"detail": "The current password is incorrect."}
        )

        at = new_app(auth=self.PENDING).run()
        self.submit(at, current="wrong")

        self.assertEqual(at.error[0].value, "The current password is incorrect.")
        self.assertEqual(len(at.chat_input), 0)

    @respx.mock
    def test_expired_session_during_change_returns_to_login(self):
        respx.post(f"{BASE}/auth/change-password").respond(401, json={"detail": "expired"})
        respx.post(f"{BASE}/auth/refresh").respond(401, json={"detail": "expired"})

        at = new_app(auth=self.PENDING).run()
        self.submit(at)

        self.assertEqual([t.label for t in at.text_input], ["Email", "Password"])
        self.assertIn("session expired", texts(at.info))

    @respx.mock
    def test_sign_out_from_the_password_screen(self):
        at = new_app(auth=self.PENDING).run()
        next(b for b in at.button if b.label == "Sign out").click().run()

        self.assertEqual([t.label for t in at.text_input], ["Email", "Password"])


class TestExpiredTokens(unittest.TestCase):
    @respx.mock
    def test_expired_access_token_is_refreshed_transparently(self):
        models = respx.get(f"{BASE}/models").mock(
            side_effect=[
                httpx.Response(401, json={"detail": "expired"}),
                httpx.Response(200, json=ONE),
            ]
        )
        refresh = respx.post(f"{BASE}/auth/refresh").respond(json=PAIR)

        at = new_app().run()

        self.assertFalse(at.exception)
        self.assertEqual(
            json.loads(refresh.calls.last.request.content), {"refresh_token": "refresh-1"}
        )
        self.assertEqual(models.calls.last.request.headers["authorization"], "Bearer access-2")
        self.assertEqual(len(at.chat_input), 1)
        self.assertEqual(at.session_state.auth["refresh_token"], "refresh-2")

    @respx.mock
    def test_failed_refresh_signs_out_with_a_notice(self):
        respx.get(f"{BASE}/models").respond(401, json={"detail": "expired"})
        respx.post(f"{BASE}/auth/refresh").respond(401, json={"detail": "expired"})

        at = new_app().run()

        self.assertEqual([t.label for t in at.text_input], ["Email", "Password"])
        self.assertIn("session expired", texts(at.info))
        self.assertNotIn("auth", at.session_state)

    @respx.mock
    def test_token_rejected_again_after_refresh_signs_out(self):
        respx.get(f"{BASE}/models").respond(401, json={"detail": "expired"})
        respx.post(f"{BASE}/auth/refresh").respond(json=PAIR)

        at = new_app().run()

        self.assertEqual([t.label for t in at.text_input], ["Email", "Password"])

    @respx.mock
    def test_expired_token_when_asking_refreshes_and_retries(self):
        respx.get(f"{BASE}/models").respond(json=ONE)
        ask = respx.post(f"{BASE}/chat").mock(
            side_effect=[
                httpx.Response(401, json={"detail": "expired"}),
                httpx.Response(200, json=CHAT_RESULT),
            ]
        )
        respx.post(f"{BASE}/auth/refresh").respond(json=PAIR)

        at = new_app().run()
        at.chat_input[0].set_value("hi").run()

        self.assertFalse(at.exception)
        self.assertEqual(ask.calls.last.request.headers["authorization"], "Bearer access-2")
        self.assertIn("What RAG is.", texts(at.markdown))


if __name__ == "__main__":
    unittest.main()
