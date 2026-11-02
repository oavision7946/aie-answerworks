import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app.db.session import get_engine
from app.main import app


class TestLiveness(unittest.TestCase):
    def tearDown(self):
        app.dependency_overrides.clear()

    def test_ok_without_touching_the_database(self):
        app.dependency_overrides[get_engine] = lambda: create_engine("sqlite:////no/such/dir/db")

        response = TestClient(app).get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})


if __name__ == "__main__":
    unittest.main()
