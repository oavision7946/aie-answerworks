import unittest
from datetime import timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.security import TokenType
from app.db.models import Role
from app.db.repositories import user_repo
from tests.auth_helpers import PASSWORD, AuthTestCase


class TestLogin(AuthTestCase):
    def test_returns_token_pair_that_authenticates(self):
        self.add_user("ana@example.com")

        response = self.login("ana@example.com")

        body = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["token_type"], "bearer")
        self.assertEqual(body["expires_in"], self.settings.app.auth.access_token_ttl_minutes * 60)
        self.assertFalse(body["must_change_password"])
        me = self.client.get(
            "/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"}
        )
        self.assertEqual(me.json()["email"], "ana@example.com")
        self.assertNotIn("password_hash", me.text)
        self.assertNotIn("argon2", me.text)

    def test_email_is_case_and_space_insensitive(self):
        self.add_user("ana@example.com")

        self.assertEqual(self.login("  ANA@Example.com ").status_code, 200)

    def test_wrong_password_and_unknown_email_are_indistinguishable(self):
        self.add_user("ana@example.com")

        wrong = self.login("ana@example.com", "wrong password!")
        unknown = self.login("nobody@example.com")

        self.assertEqual(wrong.status_code, 401)
        self.assertEqual(wrong.json(), unknown.json())
        self.assertEqual(unknown.status_code, 401)

    def test_deactivated_user_cannot_log_in(self):
        self.add_user("ana@example.com", is_active=False)

        response = self.login("ana@example.com")

        self.assertEqual(response.status_code, 403)

    def test_deactivated_with_wrong_password_still_looks_like_bad_credentials(self):
        self.add_user("ana@example.com", is_active=False)

        self.assertEqual(self.login("ana@example.com", "wrong password!").status_code, 401)

    def test_reports_pending_password_change(self):
        self.add_user("ana@example.com", must_change_password=True)

        self.assertTrue(self.login("ana@example.com").json()["must_change_password"])

    def test_malformed_body_is_rejected(self):
        self.assertEqual(self.client.post("/auth/login", json={"email": "a@b.co"}).status_code, 422)
        self.assertEqual(self.client.post("/auth/login", json={}).status_code, 422)

    def test_503_when_jwt_secret_is_not_configured(self):
        self.settings.env.jwt_secret = ""
        self.add_user("ana@example.com")

        with self.assertLogs("app.services.auth_service", level="ERROR"):
            response = self.login("ana@example.com")

        self.assertEqual(response.status_code, 503)


class TestRefresh(AuthTestCase):
    def refresh(self, token):
        return self.client.post("/auth/refresh", json={"refresh_token": token})

    def test_refresh_issues_new_pair(self):
        user = self.add_user()
        pair = self.login().json()

        response = self.refresh(pair["refresh_token"])

        self.assertEqual(response.status_code, 200)
        new = response.json()
        me = self.client.get("/auth/me", headers={"Authorization": f"Bearer {new['access_token']}"})
        self.assertEqual(me.json()["id"], str(user.id))

    def test_access_token_cannot_be_used_to_refresh(self):
        user = self.add_user()

        self.assertEqual(self.refresh(self.token(user)).status_code, 401)

    def test_refresh_token_cannot_be_used_as_access_token(self):
        user = self.add_user()
        headers = self.headers(user, kind=TokenType.REFRESH)

        self.assertEqual(self.client.get("/auth/me", headers=headers).status_code, 401)

    def test_expired_and_garbage_refresh_tokens(self):
        user = self.add_user()
        expired = self.token(user, TokenType.REFRESH, timedelta(seconds=-5))

        self.assertEqual(self.refresh(expired).status_code, 401)
        self.assertEqual(self.refresh("garbage").status_code, 401)

    def test_deactivated_user_cannot_refresh(self):
        self.add_user()
        pair = self.login().json()
        self.deactivate("user@example.com")

        self.assertEqual(self.refresh(pair["refresh_token"]).status_code, 403)

    def test_token_for_deleted_user_is_rejected(self):
        user = self.add_user()
        token = self.token(user, TokenType.REFRESH)
        with self.engine.begin() as conn:
            conn.execute(text("DELETE FROM users"))

        self.assertEqual(self.refresh(token).status_code, 401)

    def test_503_when_jwt_secret_is_not_configured(self):
        self.settings.env.jwt_secret = ""

        with self.assertLogs("app.services.auth_service", level="ERROR"):
            response = self.refresh("anything")

        self.assertEqual(response.status_code, 503)

    def deactivate(self, email):
        with Session(self.engine) as db:
            user = user_repo.get_by_email(db, email)
            user.is_active = False
            user_repo.save(db, user)


class TestMe(AuthTestCase):
    def test_requires_a_token(self):
        response = self.client.get("/auth/me")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.headers["www-authenticate"], "Bearer")

    def test_works_while_password_change_is_pending(self):
        user = self.add_user(must_change_password=True)

        response = self.client.get("/auth/me", headers=self.headers(user))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["must_change_password"])


class TestChangePassword(AuthTestCase):
    NEW = "a brand new passphrase"

    def change(self, user, current=PASSWORD, new=NEW):
        return self.client.post(
            "/auth/change-password",
            headers=self.headers(user),
            json={"current_password": current, "new_password": new},
        )

    def test_changes_password_and_clears_flag(self):
        user = self.add_user("ana@example.com", must_change_password=True)

        self.assertEqual(self.change(user).status_code, 204)

        self.assertEqual(self.login("ana@example.com", PASSWORD).status_code, 401)
        login = self.login("ana@example.com", self.NEW)
        self.assertEqual(login.status_code, 200)
        self.assertFalse(login.json()["must_change_password"])
        self.assertFalse(self.get_user("ana@example.com").must_change_password)

    def test_wrong_current_password(self):
        user = self.add_user()

        self.assertEqual(self.change(user, current="not my password").status_code, 400)
        self.assertEqual(self.login().status_code, 200)

    def test_new_password_must_differ_and_be_long_enough(self):
        user = self.add_user()

        self.assertEqual(self.change(user, new=PASSWORD).status_code, 400)
        self.assertEqual(self.change(user, new="short").status_code, 422)

    def test_requires_authentication(self):
        response = self.client.post(
            "/auth/change-password", json={"current_password": "x", "new_password": self.NEW}
        )

        self.assertEqual(response.status_code, 401)


class TestRegistrationIsRemoved(AuthTestCase):
    def test_register_returns_404(self):
        for method in (self.client.post, self.client.get):
            response = method("/auth/register")
            self.assertEqual(response.status_code, 404)

    def test_no_self_service_role_escalation_on_login_body(self):
        response = self.client.post(
            "/auth/login", json={"email": "a@b.co", "password": "x", "role": Role.ADMIN}
        )

        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
