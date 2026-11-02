import unittest
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.core.telemetry import telemetry
from app.db.models import Corpus
from app.db.session import get_engine
from app.main import app
from app.services import status_service
from app.services.llm.registry import ProviderRegistry, get_registry
from tests.helpers import REQUEST, provider_config
from tests.rag_helpers import PENGUINS, RagTestCase


class StatusTestCase(RagTestCase):
    def setUp(self):
        super().setUp()
        telemetry.reset()
        self.addCleanup(telemetry.reset)
        # The shipped config keeps the fake provider off; the tests run with it on.
        self.settings.providers.providers["fake"] = provider_config()

    def stamp(self, revision=None):
        """Record a schema version, as `alembic upgrade head` would."""
        with self.engine.begin() as connection:
            connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32))"))
            connection.execute(
                text("INSERT INTO alembic_version VALUES (:v)"),
                {"v": revision or status_service.schema_head()},
            )


class TestReadiness(StatusTestCase):
    def test_ready_when_every_dependency_is_in_place(self):
        self.stamp()

        response = self.client.get("/health/ready")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "status": "ok",
                "checks": {
                    "database": "ok",
                    "migrations": "ok",
                    "auth": "ok",
                    "providers": "ok",
                },
            },
        )

    def test_each_missing_dependency_makes_it_unavailable(self):
        self.stamp()
        cases = {
            "migrations": lambda: self.stamp_old(),
            "auth": lambda: setattr(self.settings.env, "jwt_secret", ""),
            "providers": lambda: app.dependency_overrides.__setitem__(
                get_registry, lambda: ProviderRegistry({}, "", REQUEST)
            ),
        }
        for name, break_it in cases.items():
            with self.subTest(check=name):
                break_it()
                response = self.client.get("/health/ready")
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.json()["status"], "degraded")
                self.assertEqual(response.json()["checks"][name], "unavailable")
                self.setUp()
                self.stamp()

    def stamp_old(self):
        with self.engine.begin() as connection:
            connection.execute(text("UPDATE alembic_version SET version_num = '0001'"))

    def test_a_schema_that_was_never_migrated_is_not_ready(self):
        body = self.client.get("/health/ready").json()  # no alembic_version table at all

        self.assertEqual(body["checks"]["migrations"], "unavailable")
        self.assertEqual(body["checks"]["database"], "ok")

    def test_an_unreachable_database_reports_no_internal_detail(self):
        app.dependency_overrides[get_engine] = lambda: create_engine("sqlite:////no/such/dir/db")

        with self.assertLogs("app.services.status_service", level="ERROR"):
            response = self.client.get("/health/ready")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["checks"]["database"], "unavailable")
        self.assertNotIn("/no/such", response.text)


class TestSystemStatus(StatusTestCase):
    def status(self, user=None):
        headers = self.as_user(user or self.admin)
        return self.client.get("/admin/status", headers=headers)

    def test_only_administrators_may_read_it(self):
        self.assertEqual(self.client.get("/admin/status").status_code, 401)
        self.assertEqual(self.status(self.alice).status_code, 403)

    def test_reports_database_providers_models_counts_and_requests(self):
        self.stamp()
        self.chat(self.alice, "hello")
        self.upload(self.alice, content=PENGUINS)

        body = self.status().json()

        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["environment"], self.settings.app.app.environment)
        self.assertGreaterEqual(body["uptime_seconds"], 0)
        database = body["database"]
        self.assertEqual(database["status"], "ok")
        self.assertTrue(database["migrated"])
        self.assertEqual(database["revision"], database["head"])
        self.assertIsNone(database["pgvector"])  # SQLite
        self.assertTrue(body["auth_configured"])
        providers = {p["name"]: p for p in body["providers"]}
        self.assertTrue(providers["fake"]["loaded"])
        self.assertTrue(providers["fake"]["default"])
        self.assertEqual(body["counts"]["users"], 3)
        self.assertEqual(body["counts"]["conversations"], 1)
        self.assertEqual(body["counts"]["documents"], 1)
        self.assertGreater(body["counts"]["chunks"], 0)
        models = {m["name"]: m["available"] for m in body["embedding_models"]}
        self.assertEqual(models, {"fake-a": True, "fake-b": True, "offline": False})
        self.assertGreaterEqual(body["requests"]["total"], 2)  # the chat and the upload
        self.assertIn("2xx", body["requests"]["by_status"])
        self.assertIsNotNone(body["requests"]["average_ms"])

    def test_configured_providers_that_did_not_load_say_why_and_calls_are_counted(self):
        self.stamp()
        self.chat(self.alice, "hello")
        self.upload(self.alice, content=PENGUINS)
        self.provider.embed = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down"))
        self.upload(self.alice, name="b.txt", content=PENGUINS + " More.")

        providers = {p["name"]: p for p in self.status().json()["providers"]}

        missing = next(p for p in providers.values() if not p["loaded"])
        self.assertRegex(missing["reason"], r"^[A-Z_]+ is not set$")
        calls = {c["operation"]: c for c in providers["fake"]["calls"]}
        self.assertEqual((calls["complete"]["ok"], calls["complete"]["error"]), (1, 0))
        self.assertEqual((calls["embed"]["ok"], calls["embed"]["error"]), (1, 1))
        self.assertIsNotNone(calls["embed"]["last_error_at"])
        self.assertIsNotNone(calls["complete"]["average_ms"])

    def test_a_scheduled_corpus_that_missed_its_refresh_is_overdue(self):
        self.stamp()
        old = datetime.now(UTC) - timedelta(minutes=500)
        with Session(self.engine) as db:
            db.add_all(
                [
                    Corpus(
                        name="late",
                        refresh_minutes=60,
                        source_config={"type": "url", "urls": ["https://a.test"]},
                        last_ingested_at=old.replace(tzinfo=None),
                        last_ingest_error="1 item(s) could not be ingested: x.",
                    ),
                    Corpus(
                        name="never",
                        refresh_minutes=60,
                        source_config={"type": "url", "urls": ["https://a.test"]},
                    ),
                    Corpus(name="manual", source_config={}),
                ]
            )
            db.commit()

        body = self.status().json()

        corpora = {c["name"]: c for c in body["corpora"]}
        self.assertTrue(corpora["late"]["overdue"])
        self.assertEqual(
            corpora["late"]["last_ingest_error"], "1 item(s) could not be ingested: x."
        )
        self.assertTrue(corpora["never"]["overdue"])
        self.assertFalse(corpora["manual"]["overdue"])
        self.assertEqual(body["status"], "degraded")

    def test_without_a_database_the_status_still_answers(self):
        broken = create_engine("sqlite:////no/such/dir/db")
        with Session(self.engine) as db, self.assertLogs("app.services.status_service", "ERROR"):
            result = status_service.system_status(db, broken, self.settings, self.registry)

        self.assertEqual(result.status, "degraded")
        self.assertEqual(result.database.status, "unavailable")
        self.assertEqual((result.counts, result.corpora), ({}, []))


class TestMetrics(StatusTestCase):
    def setUp(self):
        super().setUp()
        self.stamp()

    def test_off_until_a_token_is_configured(self):
        self.assertEqual(self.client.get("/metrics").status_code, 404)

    def test_needs_the_token_and_then_speaks_prometheus(self):
        self.settings.env.metrics_token = "scrape-token"
        self.chat(self.alice, "hello")
        with Session(self.engine) as db:
            db.add(
                Corpus(
                    name='he said "hi"',
                    refresh_minutes=5,
                    source_config={"type": "url", "urls": ["https://a.test"]},
                    last_ingested_at=datetime.now(UTC),
                )
            )
            db.commit()

        self.assertEqual(self.client.get("/metrics").status_code, 401)
        wrong = self.client.get("/metrics", headers={"Authorization": "Bearer nope"})
        self.assertEqual(wrong.status_code, 401)
        ok = self.client.get("/metrics", headers={"Authorization": "Bearer scrape-token"})

        self.assertEqual(ok.status_code, 200)
        self.assertTrue(ok.headers["content-type"].startswith("text/plain"))
        lines = ok.text.splitlines()
        self.assertIn("answerworks_up 1", lines)
        self.assertIn("answerworks_ready 1", lines)
        self.assertIn("answerworks_database_up 1", lines)
        self.assertIn('answerworks_rows{kind="conversations"} 1', lines)
        self.assertTrue(
            any(line.startswith("answerworks_requests_total{status=") for line in lines)
        )
        self.assertIn(
            'answerworks_corpus_overdue{corpus="he said \\"hi\\""} 0', lines
        )  # quotes are escaped
        self.assertTrue(
            any(
                line.startswith("answerworks_corpus_last_ingested_timestamp_seconds")
                for line in lines
            )
        )
        self.assertNotIn("True", ok.text)


class TestTelemetry(unittest.TestCase):
    def setUp(self):
        telemetry.reset()
        self.addCleanup(telemetry.reset)

    def test_counts_requests_by_status_class(self):
        telemetry.request(200, 0.1)
        telemetry.request(204, 0.3)
        telemetry.request(503, 0.2)

        snapshot = telemetry.snapshot()

        self.assertEqual(snapshot["requests_by_status"], {"2xx": 2, "5xx": 1})
        self.assertEqual(snapshot["requests_total"], 3)
        self.assertAlmostEqual(snapshot["request_seconds"], 0.6)

    def test_counts_provider_calls_and_remembers_the_last_outcomes(self):
        telemetry.provider_call("openai", "embed", True, 0.5)
        telemetry.provider_call("openai", "embed", False, 0.5)

        stats = telemetry.snapshot()["providers"][("openai", "embed")]

        self.assertEqual((stats.ok, stats.error, stats.seconds), (1, 1, 1.0))
        self.assertIsNotNone(stats.last_success_at)
        self.assertIsNotNone(stats.last_error_at)
        stats.ok = 99  # the snapshot is a copy
        self.assertEqual(telemetry.snapshot()["providers"][("openai", "embed")].ok, 1)

    def test_reset_starts_over(self):
        telemetry.request(200, 0.1)
        telemetry.reset()

        self.assertEqual(telemetry.snapshot()["requests_total"], 0)
        self.assertLess(telemetry.uptime_seconds, 5)


if __name__ == "__main__":
    unittest.main()
