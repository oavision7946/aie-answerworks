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

from app.db.base import Base
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

    def test_upgrade_creates_users_table_matching_the_models(self):
        command.upgrade(alembic_config(self.url), "head")

        engine = create_db_engine(self.url)
        self.assertIn("users", inspect(engine).get_table_names())
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

    def test_downgrade_removes_users_table(self):
        cfg = alembic_config(self.url)
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "base")

        self.assertNotIn("users", inspect(create_db_engine(self.url)).get_table_names())

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
            connection.exec_driver_sql("DROP TABLE IF EXISTS users, alembic_version CASCADE")
            connection.exec_driver_sql("DROP TYPE IF EXISTS user_role")
        engine.dispose()


if __name__ == "__main__":
    unittest.main()
