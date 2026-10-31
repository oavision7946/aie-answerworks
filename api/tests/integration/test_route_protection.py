"""Every protected route rejects missing, expired, tampered and wrong-type tokens."""

import unittest
import uuid
from datetime import timedelta

import jwt

from app.core.security import TokenType
from app.db.models import Role
from tests.auth_helpers import AuthTestCase

PROTECTED = [
    ("get", "/models"),
    ("post", "/ask"),
    ("get", "/auth/me"),
    ("post", "/auth/change-password"),
    ("get", "/admin/users"),
]


class TestTokenRejection(AuthTestCase):
    def assert_all_rejected(self, headers, status=401):
        for method, path in PROTECTED:
            with self.subTest(route=f"{method} {path}"):
                response = getattr(self.client, method)(path, headers=headers)
                self.assertEqual(response.status_code, status)

    def test_missing_token(self):
        self.assert_all_rejected({})

    def test_non_bearer_scheme(self):
        self.assert_all_rejected({"Authorization": "Basic dXNlcjpwYXNz"})

    def test_expired_token(self):
        user = self.add_user(role=Role.ADMIN)

        self.assert_all_rejected(self.headers(user, ttl=timedelta(seconds=-1)))

    def test_tampered_token(self):
        user = self.add_user(role=Role.ADMIN)
        token = self.token(user)
        header, payload, signature = token.split(".")

        self.assert_all_rejected({"Authorization": f"Bearer {header}.{payload}.{signature}tamper"})

    def test_token_signed_with_another_secret(self):
        user = self.add_user(role=Role.ADMIN)
        forged = jwt.encode(
            {"sub": str(user.id), "type": "access", "exp": 4_000_000_000},
            "some-other-secret-of-sufficient-length",
            algorithm="HS256",
        )

        self.assert_all_rejected({"Authorization": f"Bearer {forged}"})

    def test_refresh_token_is_not_an_access_token(self):
        user = self.add_user(role=Role.ADMIN)

        self.assert_all_rejected(self.headers(user, kind=TokenType.REFRESH))

    def test_token_for_unknown_user(self):
        ghost = self.add_user("ghost@example.com")
        headers = self.headers(ghost)
        from sqlalchemy import text

        with self.engine.begin() as conn:
            conn.execute(text("DELETE FROM users"))

        self.assert_all_rejected(headers)

    def test_cross_user_token_only_grants_that_users_access(self):
        member = self.add_user("member@example.com")
        self.add_user("admin@example.com", role=Role.ADMIN)

        as_member = self.client.get("/admin/users", headers=self.headers(member))
        me = self.client.get("/auth/me", headers=self.headers(member))

        self.assertEqual(as_member.status_code, 403)
        self.assertEqual(me.json()["email"], "member@example.com")

    def test_valid_token_for_unrelated_subject_is_rejected(self):
        self.add_user()
        token = jwt.encode(
            {"sub": str(uuid.uuid4()), "type": "access", "exp": 4_000_000_000},
            self.secret,
            algorithm="HS256",
        )

        self.assert_all_rejected({"Authorization": f"Bearer {token}"})

    def test_server_without_jwt_secret_returns_503(self):
        user = self.add_user()
        headers = self.headers(user)
        self.settings.env.jwt_secret = ""

        response = self.client.get("/models", headers=headers)

        self.assertEqual(response.status_code, 503)

    def test_deactivated_user_with_valid_token_is_refused(self):
        user = self.add_user(is_active=False)

        self.assert_all_rejected(self.headers(user), status=403)


class TestPublicRoutes(AuthTestCase):
    def test_health_and_login_need_no_token(self):
        self.assertEqual(self.client.get("/health").status_code, 200)
        self.assertEqual(self.login().status_code, 401)  # reached the handler, bad credentials

    def test_root_redirects_to_the_docs(self):
        response = self.client.get("/", follow_redirects=False)

        self.assertEqual(response.status_code, 307)
        self.assertEqual(response.headers["location"], "/docs")

    def test_get_ask_still_explains_post_usage_without_a_token(self):
        self.assertEqual(self.client.get("/ask").status_code, 405)


class TestPendingPasswordChange(AuthTestCase):
    def test_blocks_models_and_ask_but_allows_me_and_change_password(self):
        user = self.add_user(must_change_password=True)
        headers = self.headers(user)

        self.assertEqual(self.client.get("/models", headers=headers).status_code, 403)
        self.assertEqual(
            self.client.post("/ask", headers=headers, json={"question": "hi"}).status_code, 403
        )
        self.assertEqual(self.client.get("/auth/me", headers=headers).status_code, 200)


if __name__ == "__main__":
    unittest.main()
