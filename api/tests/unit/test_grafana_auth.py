import unittest
import uuid
from datetime import UTC, datetime, timedelta

import jwt

from app.core import grafana_auth
from app.core.grafana_auth import (
    GrafanaTokenType,
    grafana_assertion,
    launch_token,
    redeem_launch_token,
    session_token,
    session_user_id,
)
from app.core.security import JWT_ALGORITHM, SecretNotConfiguredError, TokenError

SECRET = "a-monitoring-secret-that-is-long-enough"
USER_ID = uuid.uuid4()


def forged(claims, secret=SECRET):
    now = datetime.now(UTC)
    return jwt.encode(
        {"iat": now, "exp": now + timedelta(minutes=1), **claims}, secret, algorithm=JWT_ALGORITHM
    )


class TestLaunchToken(unittest.TestCase):
    def setUp(self):
        grafana_auth.reset()
        self.addCleanup(grafana_auth.reset)

    def test_it_names_the_user_and_works_once(self):
        token = launch_token(USER_ID, SECRET)

        self.assertEqual(redeem_launch_token(token, SECRET), USER_ID)
        with self.assertRaisesRegex(TokenError, "already used"):
            redeem_launch_token(token, SECRET)

    def test_every_token_is_different(self):
        self.assertNotEqual(launch_token(USER_ID, SECRET), launch_token(USER_ID, SECRET))

    def test_it_is_short_lived(self):
        claims = jwt.decode(launch_token(USER_ID, SECRET), SECRET, algorithms=[JWT_ALGORITHM])

        self.assertEqual(claims["exp"] - claims["iat"], 300)

    def test_other_kinds_of_token_do_not_open_it(self):
        for token in (
            session_token(USER_ID, SECRET),
            grafana_assertion("a@example.com", SECRET),
            forged({"sub": str(USER_ID), "type": "access", "jti": "x"}),
        ):
            with self.subTest(token=token[:12]):
                with self.assertRaises(TokenError):
                    redeem_launch_token(token, SECRET)

    def test_expired_forged_and_malformed_tokens_are_refused(self):
        cases = {
            "expired": forged(
                {"sub": str(USER_ID), "type": "monitoring_launch", "jti": "a", "exp": 1}
            ),
            "other secret": launch_token(USER_ID, "another-secret-that-is-long-enough"),
            "not a token": "nonsense",
            "no id": forged({"sub": str(USER_ID), "type": "monitoring_launch"}),
            "bad subject": forged({"sub": "nobody", "type": "monitoring_launch", "jti": "b"}),
        }
        for name, token in cases.items():
            with self.subTest(case=name):
                with self.assertRaises(TokenError):
                    redeem_launch_token(token, SECRET)

    def test_remembered_ids_are_dropped_once_they_expire(self):
        redeem_launch_token(launch_token(USER_ID, SECRET), SECRET)
        grafana_auth._used["old"] = 1.0

        redeem_launch_token(launch_token(USER_ID, SECRET), SECRET)

        self.assertNotIn("old", grafana_auth._used)
        self.assertEqual(len(grafana_auth._used), 2)

    def test_a_short_secret_is_refused(self):
        with self.assertRaisesRegex(SecretNotConfiguredError, "MONITORING_JWT_SECRET"):
            launch_token(USER_ID, "short")
        with self.assertRaises(SecretNotConfiguredError):
            redeem_launch_token("x", "")


class TestSessionToken(unittest.TestCase):
    def test_it_names_the_user_for_an_hour(self):
        token = session_token(USER_ID, SECRET)
        claims = jwt.decode(token, SECRET, algorithms=[JWT_ALGORITHM])

        self.assertEqual(session_user_id(token, SECRET), USER_ID)
        self.assertEqual(claims["exp"] - claims["iat"], 3600)

    def test_a_launch_token_is_not_a_session(self):
        with self.assertRaises(TokenError):
            session_user_id(launch_token(USER_ID, SECRET), SECRET)


class TestAssertion(unittest.TestCase):
    def test_grafana_sees_a_viewer_for_a_minute(self):
        claims = jwt.decode(
            grafana_assertion("a@example.com", SECRET), SECRET, algorithms=[JWT_ALGORITHM]
        )

        self.assertEqual(claims["sub"], "a@example.com")
        self.assertEqual(claims["role"], "Viewer")
        self.assertEqual(claims["iss"], "answerworks")
        self.assertEqual(claims["exp"] - claims["iat"], 60)
        self.assertEqual(GrafanaTokenType.LAUNCH.value, "monitoring_launch")


if __name__ == "__main__":
    unittest.main()
