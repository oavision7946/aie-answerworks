"""Shared fixtures for auth tests: in-memory database, test settings, users and tokens."""

import unittest
from datetime import timedelta

from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core import security
from app.core.security import TokenType, create_token
from app.core.settings import Settings, get_settings, load_settings
from app.db.base import Base
from app.db.models import Role, User
from app.db.repositories import user_repo
from app.db.session import get_engine, get_session
from app.main import app

SECRET = "test-secret-with-more-than-32-characters"
PASSWORD = "correct horse battery"


class AuthTestCase(unittest.TestCase):
    """An app wired to a fresh SQLite database; `self.client` talks to the real routes."""

    secret = SECRET

    def setUp(self):
        # Cheap Argon2 parameters keep the suite fast; hashes stay self-describing.
        fast = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1)
        original, security._hasher = security._hasher, fast
        self.addCleanup(setattr, security, "_hasher", original)

        self.engine = create_engine(
            "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
        )
        Base.metadata.create_all(self.engine)
        self.settings: Settings = load_settings()
        self.settings.env.jwt_secret = self.secret

        def session():
            with Session(self.engine, expire_on_commit=False) as db:
                yield db

        app.dependency_overrides[get_session] = session
        app.dependency_overrides[get_engine] = lambda: self.engine
        app.dependency_overrides[get_settings] = lambda: self.settings
        self.addCleanup(app.dependency_overrides.clear)
        self.client = TestClient(app)

    def add_user(
        self,
        email="user@example.com",
        password=PASSWORD,
        role=Role.USER,
        is_active=True,
        must_change_password=False,
    ) -> User:
        with Session(self.engine, expire_on_commit=False) as db:
            user = user_repo.create(
                db, email, security.hash_password(password), role, must_change_password
            )
            if not is_active:
                user.is_active = False
                user_repo.save(db, user)
        return user

    def get_user(self, email) -> User:
        with Session(self.engine, expire_on_commit=False) as db:
            user = user_repo.get_by_email(db, email)
        assert user is not None
        return user

    def token(self, user: User, kind=TokenType.ACCESS, ttl=timedelta(minutes=5)) -> str:
        return create_token(user.id, kind, ttl, self.secret)

    def headers(self, user: User, **kwargs) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token(user, **kwargs)}"}

    def login(self, email="user@example.com", password=PASSWORD):
        return self.client.post("/auth/login", json={"email": email, "password": password})
