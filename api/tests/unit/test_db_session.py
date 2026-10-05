import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from app.db import session


class TestDbSession(unittest.TestCase):
    def test_check_database_true_for_working_engine(self):
        self.assertTrue(session.check_database(create_engine("sqlite://")))

    def test_check_database_false_for_unreachable_engine(self):
        self.assertFalse(session.check_database(create_engine("sqlite:////no/such/dir/x.db")))

    def test_postgres_engines_get_a_connect_timeout(self):
        with patch.object(session, "create_engine") as create:
            session.create_db_engine("postgresql+psycopg://u:p@h/db")
            session.create_db_engine("sqlite://")

        self.assertEqual(
            create.call_args_list[0].kwargs["connect_args"],
            {"connect_timeout": session.CONNECT_TIMEOUT_SECONDS},
        )
        self.assertEqual(create.call_args_list[1].kwargs["connect_args"], {})

    def test_get_session_yields_a_usable_session_and_closes_it(self):
        engine = create_engine("sqlite://", poolclass=StaticPool)
        with patch.object(session, "get_engine", return_value=engine):
            generator = session.get_session()
            db = next(generator)
            self.assertEqual(db.execute(text("SELECT 1")).scalar(), 1)
            with self.assertRaises(StopIteration):
                next(generator)

    def test_get_engine_is_built_from_settings_and_cached(self):
        session.get_engine.cache_clear()
        try:
            with patch.object(session, "create_db_engine") as create:
                session.get_engine()
                session.get_engine()
            create.assert_called_once()
        finally:
            session.get_engine.cache_clear()


if __name__ == "__main__":
    unittest.main()
