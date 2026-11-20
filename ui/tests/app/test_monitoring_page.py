"""Monitoring page: the health summary and the way into the dashboards."""

import unittest

import respx

from app import config
from tests.app.helpers import (
    ADMIN_SIGNED_IN,
    MONITOR_SIGNED_IN,
    ONE,
    RAG_OPTIONS,
    STATUS,
    new_app,
)

BASE = config.API_BASE_URL.rstrip("/")
PAGE = "views/monitoring.py"
LINK = {"login_url": "http://api.test/monitoring/login?token=abc", "expires_in": 300}


class TestMonitoringPage(unittest.TestCase):
    def setUp(self):
        mock = respx.mock(assert_all_called=False)
        mock.start()
        self.addCleanup(mock.stop)
        mock.get(f"{BASE}/models").respond(json=ONE)
        mock.get(f"{BASE}/rag/options").respond(json=RAG_OPTIONS)
        self.status = mock.get(f"{BASE}/monitoring/status").respond(json=STATUS)
        self.token = mock.post(f"{BASE}/monitoring/token").respond(json=LINK)
        self.mock = mock

    def open(self, auth=MONITOR_SIGNED_IN):
        at = new_app(auth=auth).run()
        at.switch_page(PAGE).run()
        return at

    def text(self, at):
        return " ".join(m.value for m in [*at.markdown, *at.caption, *at.success, *at.warning])

    def open_dashboards(self, at):
        [button] = [b for b in at.button if b.label == "Open dashboards"]
        button.click().run()
        return at

    def test_monitors_see_a_summary_of_the_system(self):
        at = self.open()

        self.assertFalse(at.exception)
        text = self.text(at)
        self.assertIn("## Monitoring", text)
        self.assertIn("Everything the API needs is working.", text)
        self.assertIn("Version 0.1.0 · development · up for 1h 2m 5s", text)
        self.assertIn("Requests since the API started: 40", text)
        self.assertEqual(
            {m.label: m.value for m in at.metric},
            {
                "Database": "ok",
                "Schema": "up to date",
                "Providers loaded": "1 of 2",
                "Corpora to check": "1",
            },
        )

    def test_administrators_reach_it_too(self):
        at = self.open(ADMIN_SIGNED_IN)

        self.assertFalse(at.exception)
        self.assertIn("## Monitoring", self.text(at))

    def test_problems_are_called_out(self):
        self.status.respond(
            json={
                **STATUS,
                "status": "degraded",
                "database": {**STATUS["database"], "status": "unavailable", "migrated": False},
                "providers": [],
                "corpora": [],
            }
        )

        at = self.open()

        self.assertIn("Something needs attention.", [w.value for w in at.warning])
        self.assertEqual(
            {m.label: m.value for m in at.metric},
            {
                "Database": "down",
                "Schema": "behind",
                "Providers loaded": "0 of 0",
                "Corpora to check": "0",
            },
        )

    def test_a_refused_status_is_shown_as_an_error(self):
        self.status.respond(403, json={"detail": "Monitoring access is required."})

        at = self.open()

        self.assertIn("Monitoring access is required.", [e.value for e in at.error])
        self.assertEqual(len(at.metric), 0)

    def test_no_link_is_requested_until_asked_for(self):
        at = self.open()

        self.assertFalse(self.token.called)
        self.assertEqual(len(at.get("link_button")), 0)

    def test_the_button_offers_a_one_use_link(self):
        at = self.open_dashboards(self.open())

        self.assertTrue(self.token.called)
        self.assertEqual(self.token.calls.last.request.headers["Authorization"], "Bearer access-1")
        [link] = at.get("link_button")
        self.assertEqual(link.proto.url, LINK["login_url"])
        self.assertIn("works once and for 5m 0s", self.text(at))

    def test_dashboards_that_are_not_set_up_are_explained(self):
        self.token.respond(503, json={"detail": "Dashboard sign-in is not configured."})

        at = self.open_dashboards(self.open())

        self.assertIn("Dashboard sign-in is not configured.", [i.value for i in at.info])
        self.assertEqual(len(at.get("link_button")), 0)


if __name__ == "__main__":
    unittest.main()
