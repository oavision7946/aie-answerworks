"""Admin → Users page, reached through the real navigation."""

import json
import unittest

import respx

from app import config
from tests.app.helpers import ADMIN_SIGNED_IN, ONE, new_app

BASE = config.API_BASE_URL.rstrip("/")
PAGE = "views/admin_users.py"
ROOT = {
    "id": "u-0",
    "email": "root@example.com",
    "role": "admin",
    "is_active": True,
    "must_change_password": False,
}
ANA = {
    **ROOT,
    "id": "u-1",
    "email": "ana@example.com",
    "role": "user",
    "must_change_password": True,
}


class TestAdminUsersPage(unittest.TestCase):
    def setUp(self):
        mock = respx.mock(assert_all_called=False)
        mock.start()
        self.addCleanup(mock.stop)
        mock.get(f"{BASE}/models").respond(json=ONE)
        self.users = mock.get(f"{BASE}/admin/users").respond(json=[ROOT, ANA])
        self.mock = mock

    def open(self):
        at = new_app(auth=ADMIN_SIGNED_IN).run()
        at.switch_page(PAGE).run()
        return at

    def test_lists_users(self):
        at = self.open()

        self.assertFalse(at.exception)
        rows = at.dataframe[0].value
        self.assertEqual(list(rows["Email"]), ["root@example.com", "ana@example.com"])
        self.assertEqual(list(rows["Role"]), ["admin", "user"])
        self.assertEqual(list(rows["Must change password"]), [False, True])
        self.assertEqual(self.users.calls.last.request.headers["authorization"], "Bearer access-1")

    def test_create_user(self):
        create = self.mock.post(f"{BASE}/admin/users").respond(201, json=ANA)

        at = self.open()
        at.text_input[0].set_value("ana@example.com")
        at.text_input[1].set_value("temporary pass 123")
        at.selectbox[0].select("admin")  # the Role in the create form
        next(b for b in at.button if b.label == "Create user").click().run()

        self.assertFalse(at.exception)
        self.assertEqual(
            json.loads(create.calls.last.request.content),
            {
                "email": "ana@example.com",
                "temporary_password": "temporary pass 123",
                "role": "admin",
            },
        )
        self.assertIn("Created ana@example.com", at.success[0].value)

    def test_the_monitor_role_can_be_chosen_when_creating_and_changing_users(self):
        create = self.mock.post(f"{BASE}/admin/users").respond(201, json=ANA)

        at = self.open()
        self.assertEqual(at.selectbox[0].options, ["user", "monitor", "admin"])
        at.text_input[0].set_value("ana@example.com")
        at.text_input[1].set_value("temporary pass 123")
        at.selectbox[0].select("monitor")
        next(b for b in at.button if b.label == "Create user").click().run()

        self.assertEqual(json.loads(create.calls.last.request.content)["role"], "monitor")
        at.selectbox[1].select("ana@example.com").run()  # the "User" chooser
        self.assertEqual(at.selectbox(key="role-u-1").options, ["user", "monitor", "admin"])

    def test_create_error_is_shown(self):
        self.mock.post(f"{BASE}/admin/users").respond(
            409, json={"detail": "A user with this email already exists."}
        )

        at = self.open()
        next(b for b in at.button if b.label == "Create user").click().run()

        self.assertEqual(at.error[0].value, "A user with this email already exists.")

    def test_change_role_and_deactivate_send_only_what_changed(self):
        update = self.mock.patch(f"{BASE}/admin/users/u-1").respond(json=ANA)

        at = self.open()
        at.selectbox[1].select("ana@example.com").run()  # the "User" chooser
        at.checkbox(key="active-u-1").uncheck()
        at.button(key="save-u-1").click().run()

        self.assertFalse(at.exception)
        self.assertEqual(json.loads(update.calls.last.request.content), {"is_active": False})
        self.assertIn("Updated ana@example.com", at.success[0].value)

    def test_role_change_is_sent(self):
        update = self.mock.patch(f"{BASE}/admin/users/u-1").respond(json=ANA)

        at = self.open()
        at.selectbox[1].select("ana@example.com").run()
        at.selectbox(key="role-u-1").select("admin")
        at.button(key="save-u-1").click().run()

        self.assertEqual(json.loads(update.calls.last.request.content), {"role": "admin"})

    def test_update_error_is_shown(self):
        self.mock.patch(f"{BASE}/admin/users/u-0").respond(
            400, json={"detail": "You cannot deactivate or demote your own account."}
        )

        at = self.open()
        at.checkbox(key="active-u-0").uncheck()
        at.button(key="save-u-0").click().run()

        self.assertIn("cannot deactivate", at.error[0].value)

    def test_reset_password(self):
        reset = self.mock.post(f"{BASE}/admin/users/u-1/reset-password").respond(json=ANA)

        at = self.open()
        at.selectbox[1].select("ana@example.com").run()
        at.text_input[-1].set_value("another temp pass")
        next(b for b in at.button if b.label == "Reset password").click().run()

        self.assertEqual(
            json.loads(reset.calls.last.request.content),
            {"temporary_password": "another temp pass"},
        )
        self.assertIn("Password reset for ana@example.com", at.success[0].value)

    def test_reset_error_is_shown(self):
        self.mock.post(f"{BASE}/admin/users/u-0/reset-password").respond(
            422, json={"detail": "Invalid request."}
        )

        at = self.open()
        next(b for b in at.button if b.label == "Reset password").click().run()

        self.assertEqual(at.error[0].value, "Invalid request.")

    def test_api_refusal_replaces_the_page_with_an_error(self):
        self.users.respond(403, json={"detail": "Administrator access is required."})

        at = self.open()

        self.assertEqual(at.error[0].value, "Administrator access is required.")
        self.assertEqual(len(at.dataframe), 0)


if __name__ == "__main__":
    unittest.main()
