import io
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.security import verify_password
from app.db.base import Base
from app.db.models import Role
from app.db.repositories import user_repo
from scripts import create_admin
from scripts.create_admin import BootstrapError

PASSWORD = "bootstrap passphrase"


class TestCreateAdmin(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.addCleanup(self.db.close)

    def test_creates_an_active_admin_without_forced_password_change(self):
        email = create_admin.create_admin(self.db, " Root@Example.com ", PASSWORD)

        user = user_repo.get_by_email(self.db, "root@example.com")
        self.assertEqual(email, "root@example.com")
        self.assertEqual(user.role, Role.ADMIN)
        self.assertTrue(user.is_active)
        self.assertFalse(user.must_change_password)
        self.assertTrue(verify_password(PASSWORD, user.password_hash))
        self.assertNotEqual(user.password_hash, PASSWORD)

    def test_refuses_when_an_admin_already_exists(self):
        create_admin.create_admin(self.db, "root@example.com", PASSWORD)

        with self.assertRaises(BootstrapError):
            create_admin.create_admin(self.db, "second@example.com", PASSWORD)
        self.assertIsNone(user_repo.get_by_email(self.db, "second@example.com"))

    def test_refuses_to_overwrite_an_existing_user(self):
        user_repo.create(self.db, "ana@example.com", "original-hash", Role.USER)

        with self.assertRaises(BootstrapError):
            create_admin.create_admin(self.db, "ana@example.com", PASSWORD)
        user = user_repo.get_by_email(self.db, "ana@example.com")
        self.assertEqual(user.role, Role.USER)
        self.assertEqual(user.password_hash, "original-hash")

    def test_rejects_bad_email_and_weak_password(self):
        for email, password in (("nope", PASSWORD), ("a@example.com", "short")):
            with self.subTest(email=email), self.assertRaises(BootstrapError):
                create_admin.create_admin(self.db, email, password)


class TestMain(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        patcher = patch.object(create_admin, "get_engine", return_value=self.engine)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch.object(create_admin, "load_env")
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_main(self, env, inputs=(), passwords=()):
        out, err = io.StringIO(), io.StringIO()
        with (
            patch.dict(os.environ, env, clear=False),
            patch("builtins.input", side_effect=list(inputs)),
            patch.object(create_admin, "getpass", side_effect=list(passwords)),
            redirect_stdout(out),
            redirect_stderr(err),
        ):
            code = create_admin.main()
        return code, out.getvalue(), err.getvalue()

    def test_reads_credentials_from_environment(self):
        env = {"BOOTSTRAP_ADMIN_EMAIL": "root@example.com", "BOOTSTRAP_ADMIN_PASSWORD": PASSWORD}

        code, out, _ = self.run_main(env)

        self.assertEqual(code, 0)
        self.assertIn("root@example.com", out)
        self.assertNotIn(PASSWORD, out)

    def test_prompts_for_missing_credentials(self):
        env = {"BOOTSTRAP_ADMIN_EMAIL": "", "BOOTSTRAP_ADMIN_PASSWORD": ""}

        code, _, _ = self.run_main(env, inputs=["root@example.com"], passwords=[PASSWORD])

        self.assertEqual(code, 0)
        with Session(self.engine) as db:
            self.assertIsNotNone(user_repo.get_by_email(db, "root@example.com"))

    def test_second_run_exits_nonzero_and_changes_nothing(self):
        env = {"BOOTSTRAP_ADMIN_EMAIL": "root@example.com", "BOOTSTRAP_ADMIN_PASSWORD": PASSWORD}
        self.run_main(env)

        code, _, err = self.run_main(env)

        self.assertEqual(code, 1)
        self.assertIn("nothing was changed", err)


if __name__ == "__main__":
    unittest.main()
