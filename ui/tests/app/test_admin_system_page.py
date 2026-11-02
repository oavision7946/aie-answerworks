"""Admin → System page, reached through the real navigation."""

import unittest
from datetime import UTC, datetime

import respx

from app import config
from app.components.format import ago, duration
from tests.app.helpers import ADMIN_SIGNED_IN, ONE, RAG_OPTIONS, STATUS, new_app

BASE = config.API_BASE_URL.rstrip("/")
PAGE = "views/admin_system.py"


class TestAdminSystemPage(unittest.TestCase):
    def setUp(self):
        mock = respx.mock(assert_all_called=False)
        mock.start()
        self.addCleanup(mock.stop)
        mock.get(f"{BASE}/models").respond(json=ONE)
        mock.get(f"{BASE}/rag/options").respond(json=RAG_OPTIONS)
        self.status = mock.get(f"{BASE}/admin/status").respond(json=STATUS)
        self.mock = mock

    def open(self):
        at = new_app(auth=ADMIN_SIGNED_IN).run()
        at.switch_page(PAGE).run()
        return at

    def text(self, at):
        return " ".join(m.value for m in [*at.markdown, *at.caption, *at.success, *at.warning])

    def test_shows_every_section_for_a_healthy_system(self):
        at = self.open()

        self.assertFalse(at.exception)
        text = self.text(at)
        self.assertIn("Everything the API needs is working.", text)
        self.assertIn("Version 0.1.0 · development · up for 1h 2m 5s", text)
        self.assertIn("(0004 of 0004)", text)
        self.assertIn("1.5 ms", text)
        self.assertIn("openai (default)", text)
        self.assertIn("anthropic", text)
        self.assertIn("not loaded: ANTHROPIC_API_KEY is not set", text)
        self.assertIn("Requests since start: 40 (2xx: 38, 4xx: 2) · average 12.3 ms", text)
        frames = [df.value for df in at.dataframe]
        self.assertEqual(frames[0]["Operation"].tolist(), ["complete", "embed"])
        self.assertEqual(frames[0]["Failed"].tolist(), [1, 0])
        self.assertEqual(frames[1]["Name"].tolist(), ["small"])
        corpora = frames[2]
        self.assertEqual(corpora["Refresh"].tolist(), ["every 60 min", "manual"])
        self.assertEqual(corpora["Source"].tolist(), ["url", "uploads"])
        self.assertEqual(corpora["Overdue"].tolist(), [True, False])
        self.assertEqual([m.label for m in at.metric], ["Active users", "Documents", "Users"])

    def test_problems_are_called_out(self):
        broken = {
            **STATUS,
            "status": "degraded",
            "auth_configured": False,
            "database": {**STATUS["database"], "migrated": False, "pgvector": False},
            "providers": [],
            "corpora": [],
            "requests": {"total": 0},
            "counts": {},
        }
        self.status.respond(json=broken)

        at = self.open()

        self.assertEqual(at.warning[0].value, "Something needs attention. See the sections below.")
        self.assertIn("JWT_SECRET is not set", at.error[0].value)
        self.assertIn("No provider is enabled", at.info[0].value)
        self.assertIn("needs attention", self.text(at))
        self.assertIn("No shared corpora yet.", self.text(at))
        self.assertIn("Requests since start: 0 (none yet) · average n/a", self.text(at))

    def test_database_down_and_not_postgres_are_shown_plainly(self):
        down = {
            **STATUS,
            "database": {"status": "unavailable", "head": "0004", "pgvector": None},
        }
        self.status.respond(json=down)

        at = self.open()

        text = self.text(at)
        self.assertIn("(none of 0004)", text)
        self.assertIn("n/a", text)
        self.assertIn("—", text)

    def test_errors_are_shown_and_refresh_reloads(self):
        self.status.respond(403, json={"detail": "Administrator access is required."})

        at = self.open()

        self.assertIn("Administrator access", at.error[0].value)

        self.status.respond(json=STATUS)
        at.button[0].click().run()
        self.assertEqual(len(at.error), 0)
        self.assertGreaterEqual(self.status.call_count, 2)


class TestFormat(unittest.TestCase):
    def test_duration(self):
        self.assertEqual(duration(5), "5s")
        self.assertEqual(duration(125), "2m 5s")
        self.assertEqual(duration(90061), "1d 1h 1m 1s")

    def test_ago(self):
        now = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
        self.assertEqual(ago(None), "never")
        self.assertEqual(ago("2026-11-02T11:00:00Z", now), "1h 0m 0s ago")
        self.assertEqual(ago("2026-11-02T11:59:00", now), "1m 0s ago")  # no timezone: UTC


if __name__ == "__main__":
    unittest.main()
