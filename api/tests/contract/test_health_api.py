import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.db.session import get_engine
from app.main import app


class TestHealth(unittest.TestCase):
    def tearDown(self):
        app.dependency_overrides.clear()

    def test_ok_when_database_reachable(self):
        engine = create_engine("sqlite://", poolclass=StaticPool)
        app.dependency_overrides[get_engine] = lambda: engine

        response = TestClient(app).get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "database": "ok"})

    def test_degraded_503_when_database_unreachable(self):
        engine = create_engine("sqlite:////nonexistent-dir/db.sqlite")
        app.dependency_overrides[get_engine] = lambda: engine

        with self.assertLogs("app.api.health", level="ERROR"):
            response = TestClient(app).get("/health")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"status": "degraded", "database": "unavailable"})


if __name__ == "__main__":
    unittest.main()
