import unittest
import uuid

from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import Role, User


class TestUserModel(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)

    def test_defaults(self):
        with Session(self.engine) as db:
            db.add(User(email="a@example.com", password_hash="hash"))
            db.commit()
            user = db.scalar(select(User))

        self.assertIsInstance(user.id, uuid.UUID)
        self.assertEqual(user.role, Role.USER)
        self.assertTrue(user.is_active)
        self.assertTrue(user.must_change_password)
        self.assertIsNotNone(user.created_at)

    def test_email_is_unique(self):
        with Session(self.engine) as db:
            db.add(User(email="a@example.com", password_hash="h"))
            db.commit()
            db.add(User(email="a@example.com", password_hash="h2"))
            with self.assertRaises(IntegrityError):
                db.commit()

    def test_admin_role_roundtrips(self):
        with Session(self.engine) as db:
            db.add(User(email="root@example.com", password_hash="h", role=Role.ADMIN))
            db.commit()
            self.assertEqual(db.scalar(select(User.role)), Role.ADMIN)


if __name__ == "__main__":
    unittest.main()
