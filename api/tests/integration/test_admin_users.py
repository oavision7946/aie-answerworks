import unittest
import uuid

from app.db.models import Role
from tests.auth_helpers import PASSWORD, AuthTestCase

TEMP = "temporary passphrase"


class AdminTestCase(AuthTestCase):
    def setUp(self):
        super().setUp()
        self.admin = self.add_user("admin@example.com", role=Role.ADMIN)
        self.member = self.add_user("member@example.com")
        self.target = self.add_user("target@example.com")

    def routes(self):
        """(method, path, json) for every admin route, aimed at an existing target user."""
        target = f"/admin/users/{self.target.id}"
        return [
            ("post", "/admin/users", {"email": "new@example.com", "temporary_password": TEMP}),
            ("get", "/admin/users", None),
            ("patch", target, {"is_active": True}),
            ("post", f"{target}/reset-password", {"temporary_password": TEMP}),
        ]

    def call(self, method, path, body=None, headers=None):
        return self.client.request(method.upper(), path, json=body, headers=headers)


class TestAuthorizationMatrix(AdminTestCase):
    def test_anonymous_gets_401_user_gets_403_admin_succeeds(self):
        expected_ok = {"post /admin/users": 201}
        for method, path, body in self.routes():
            key = f"{method} {path}"
            with self.subTest(route=key):
                self.assertEqual(self.call(method, path, body).status_code, 401)
                as_user = self.call(method, path, body, self.headers(self.member))
                self.assertEqual(as_user.status_code, 403)
                as_admin = self.call(method, path, body, self.headers(self.admin))
                self.assertEqual(as_admin.status_code, expected_ok.get(key, 200))

    def test_admin_with_pending_password_change_is_blocked(self):
        pending = self.add_user("pending@example.com", role=Role.ADMIN, must_change_password=True)

        response = self.client.get("/admin/users", headers=self.headers(pending))

        self.assertEqual(response.status_code, 403)
        self.assertIn("Password change", response.json()["detail"])

    def test_deactivated_admin_token_stops_working(self):
        self.client.patch(
            f"/admin/users/{self.target.id}",
            json={"role": "admin"},
            headers=self.headers(self.admin),
        )
        headers = self.headers(self.target)
        self.client.patch(
            f"/admin/users/{self.target.id}",
            json={"is_active": False},
            headers=self.headers(self.admin),
        )

        self.assertEqual(self.client.get("/admin/users", headers=headers).status_code, 403)


class TestCreateAndList(AdminTestCase):
    def create(self, **body):
        body = {"email": "new@example.com", "temporary_password": TEMP, **body}
        return self.client.post("/admin/users", json=body, headers=self.headers(self.admin))

    def test_created_user_must_change_password_before_using_the_api(self):
        response = self.create(email="  New@Example.com ")

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["email"], "new@example.com")
        self.assertEqual(body["role"], "user")
        self.assertTrue(body["must_change_password"])
        self.assertTrue(body["is_active"])
        self.assertNotIn("argon2", response.text)

        login = self.login("new@example.com", TEMP)
        self.assertEqual(login.status_code, 200)
        self.assertTrue(login.json()["must_change_password"])
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        blocked = self.client.get("/models", headers=headers)
        self.assertEqual(blocked.status_code, 403)

        changed = self.client.post(
            "/auth/change-password",
            headers=headers,
            json={"current_password": TEMP, "new_password": "my own new passphrase"},
        )
        self.assertEqual(changed.status_code, 204)
        relogin = self.login("new@example.com", "my own new passphrase").json()
        headers = {"Authorization": f"Bearer {relogin['access_token']}"}
        self.assertEqual(self.client.get("/models", headers=headers).status_code, 200)

    def test_can_create_an_admin(self):
        self.assertEqual(self.create(role="admin").json()["role"], "admin")
        self.assertEqual(
            self.create(email="watch@example.com", role="monitor").json()["role"], "monitor"
        )

    def test_duplicate_email_conflicts_case_insensitively(self):
        self.assertEqual(self.create(email="MEMBER@example.com").status_code, 409)

    def test_race_on_unique_email_is_a_conflict(self):
        from unittest.mock import patch

        from app.db.repositories import user_repo

        with patch.object(user_repo, "get_by_email", return_value=None):
            response = self.create(email="member@example.com")

        self.assertEqual(response.status_code, 409)

    def test_validation(self):
        for body in (
            {"email": "not-an-email"},
            {"temporary_password": "short"},
            {"role": "superuser"},
            {"is_admin": True},
        ):
            with self.subTest(body=body):
                self.assertEqual(self.create(**body).status_code, 422)

    def test_list_returns_all_users_without_secrets(self):
        response = self.client.get("/admin/users", headers=self.headers(self.admin))

        emails = [u["email"] for u in response.json()]
        self.assertCountEqual(
            emails, ["admin@example.com", "member@example.com", "target@example.com"]
        )
        self.assertNotIn("password_hash", response.text)


class TestUpdate(AdminTestCase):
    def patch(self, user_id, body, actor=None):
        return self.client.patch(
            f"/admin/users/{user_id}", json=body, headers=self.headers(actor or self.admin)
        )

    def test_set_role_and_deactivate(self):
        promoted = self.patch(self.target.id, {"role": "admin"}).json()
        deactivated = self.patch(self.target.id, {"is_active": False}).json()

        self.assertEqual(promoted["role"], "admin")
        self.assertFalse(deactivated["is_active"])
        self.assertEqual(self.login("target@example.com").status_code, 403)

    def test_monitor_role_can_be_granted_and_removed(self):
        granted = self.patch(self.target.id, {"role": "monitor"}).json()
        revoked = self.patch(self.target.id, {"role": "user"}).json()

        self.assertEqual(granted["role"], "monitor")
        self.assertEqual(revoked["role"], "user")

    def test_reactivate(self):
        self.patch(self.target.id, {"is_active": False})
        self.patch(self.target.id, {"is_active": True})

        self.assertEqual(self.login("target@example.com").status_code, 200)

    def test_admin_cannot_lock_themselves_out(self):
        self.assertEqual(self.patch(self.admin.id, {"is_active": False}).status_code, 400)
        self.assertEqual(self.patch(self.admin.id, {"role": "user"}).status_code, 400)
        self.assertEqual(self.patch(self.admin.id, {"role": "monitor"}).status_code, 400)
        self.assertEqual(self.patch(self.admin.id, {"role": "admin"}).status_code, 200)

    def test_unknown_user_and_bad_id(self):
        self.assertEqual(self.patch(uuid.uuid4(), {"is_active": True}).status_code, 404)
        self.assertEqual(self.patch("not-a-uuid", {"is_active": True}).status_code, 422)

    def test_unknown_fields_are_rejected(self):
        self.assertEqual(self.patch(self.target.id, {"email": "x@example.com"}).status_code, 422)


class TestResetPassword(AdminTestCase):
    def test_reset_sets_temporary_password_and_forces_change(self):
        response = self.client.post(
            f"/admin/users/{self.target.id}/reset-password",
            json={"temporary_password": TEMP},
            headers=self.headers(self.admin),
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["must_change_password"])
        self.assertEqual(self.login("target@example.com", PASSWORD).status_code, 401)
        self.assertTrue(self.login("target@example.com", TEMP).json()["must_change_password"])

    def test_unknown_user(self):
        response = self.client.post(
            f"/admin/users/{uuid.uuid4()}/reset-password",
            json={"temporary_password": TEMP},
            headers=self.headers(self.admin),
        )

        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
