"""Alembic migrations: SQLite always; real PostgreSQL when TEST_POSTGRES_URL is set."""

import os
import tempfile
import unittest
from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import Role, User
from app.db.session import create_db_engine

API_DIR = Path(__file__).resolve().parents[2]
POSTGRES_URL = os.environ.get("TEST_POSTGRES_URL")


def alembic_config(url: str) -> Config:
    cfg = Config(str(API_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


class MigrationChecks:
    url: str

    def test_upgrade_creates_tables_matching_the_models(self):
        command.upgrade(alembic_config(self.url), "head")

        engine = create_db_engine(self.url)
        self.assertTrue(
            {
                "users",
                "conversations",
                "messages",
                "corpora",
                "corpus_access",
                "documents",
                "chunks",
            }
            <= set(inspect(engine).get_table_names())
        )
        columns = {c["name"] for c in inspect(engine).get_columns("users")}
        self.assertEqual(
            columns,
            {
                "id",
                "email",
                "password_hash",
                "role",
                "is_active",
                "must_change_password",
                "created_at",
            },
        )
        with engine.connect() as connection:
            diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)
        self.assertEqual(diff, [], "models and migrations have drifted; add a migration")

    def test_chunks_record_the_embedding_model_and_splitter(self):
        command.upgrade(alembic_config(self.url), "head")

        columns = {c["name"] for c in inspect(create_db_engine(self.url)).get_columns("chunks")}

        self.assertEqual(
            columns,
            {
                "id",
                "document_id",
                "chunk_index",
                "text",
                "embedding",
                "embedding_name",
                "embedding_provider",
                "embedding_model",
                "embedding_dimensions",
                "chunking_name",
                "chunking_method",
                "chunk_size",
                "chunk_overlap",
                "created_at",
            },
        )

    def test_conversation_columns(self):
        command.upgrade(alembic_config(self.url), "head")

        inspector = inspect(create_db_engine(self.url))
        self.assertEqual(
            {c["name"] for c in inspector.get_columns("conversations")},
            {
                "id",
                "user_id",
                "title",
                "provider",
                "model",
                "use_rag",
                "corpus_ids",
                "created_at",
                "updated_at",
            },
        )
        self.assertEqual(
            {c["name"] for c in inspector.get_columns("messages")},
            {
                "id",
                "conversation_id",
                "role",
                "content",
                "provider",
                "model",
                "tokens_used",
                "latency_ms",
                "cost_usd",
                "retrieved_chunk_ids",
                "created_at",
            },
        )

    def test_downgrade_removes_tables(self):
        cfg = alembic_config(self.url)
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "0001")
        remaining = inspect(create_db_engine(self.url)).get_table_names()
        self.assertNotIn("conversations", remaining)
        self.assertNotIn("messages", remaining)
        self.assertIn("users", remaining)

        command.downgrade(cfg, "base")

        self.assertNotIn("users", inspect(create_db_engine(self.url)).get_table_names())

    def test_monitor_role_is_stored_and_downgrade_turns_it_into_user(self):
        cfg = alembic_config(self.url)
        command.upgrade(cfg, "head")
        engine = create_db_engine(self.url)
        with Session(engine) as db:
            db.add(User(email="watch@example.com", password_hash="h", role=Role.MONITOR))
            db.add(User(email="root@example.com", password_hash="h", role=Role.ADMIN))
            db.commit()

        command.downgrade(cfg, "0004")

        with engine.connect() as connection:
            roles = dict(connection.exec_driver_sql("SELECT email, role FROM users").all())
        self.assertEqual(roles, {"watch@example.com": "user", "root@example.com": "admin"})
        command.upgrade(cfg, "head")  # and back again

    def test_upgrade_is_repeatable(self):
        cfg = alembic_config(self.url)
        command.upgrade(cfg, "head")
        command.upgrade(cfg, "head")  # already at head: no-op


class TestSqliteMigrations(MigrationChecks, unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.url = f"sqlite:///{self._tmp.name}/test.db"

    def tearDown(self):
        self._tmp.cleanup()


@unittest.skipUnless(POSTGRES_URL, "set TEST_POSTGRES_URL to run against PostgreSQL")
class TestPostgresMigrations(MigrationChecks, unittest.TestCase):
    def setUp(self):
        self.url = POSTGRES_URL
        self._reset()

    def tearDown(self):
        self._reset()

    def _reset(self):
        engine = create_db_engine(self.url)
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "DROP TABLE IF EXISTS chunks, documents, corpus_access, corpora, messages, "
                "conversations, users, alembic_version CASCADE"
            )
            connection.exec_driver_sql(
                "DROP TYPE IF EXISTS user_role, message_role, document_status"
            )
        engine.dispose()


if __name__ == "__main__":
    unittest.main()
