import unittest
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.core.telemetry import telemetry
from app.db.models import Corpus, Role
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


def samples(text, name):
    """The lines of one metric family: {labels string: value}."""
    result = {}
    for line in text.splitlines():
        if line.startswith(name + "{") or line.startswith(name + " "):
            key, value = line.rsplit(" ", 1)
            result[key[len(name) :]] = float(value)
    return result


class TestTimingMetrics(StatusTestCase):
    def setUp(self):
        super().setUp()
        self.stamp()
        self.settings.env.metrics_token = "scrape-token"

    def scrape(self):
        response = self.client.get("/metrics", headers={"Authorization": "Bearer scrape-token"})
        self.assertEqual(response.status_code, 200)
        return response.text

    def test_a_chat_with_documents_is_timed_by_route_and_stage(self):
        self.upload(self.alice, "penguins.txt", PENGUINS)
        self.chat(self.alice, "where do penguins live", use_rag=True)

        text = self.scrape()

        counts = samples(text, "answerworks_request_duration_seconds_count")
        self.assertEqual(counts['{route="/chat",status="2xx"}'], 1)
        self.assertNotIn("conversation", "".join(counts))  # templates, never concrete ids
        stages = samples(text, "answerworks_stage_duration_seconds_count")
        for stage in ("chat.prepare", "rag.retrieve", "embed.query", "vector.search"):
            self.assertEqual(stages[f'{{stage="{stage}"}}'], 1, stage)
        self.assertEqual(stages['{stage="llm.complete"}'], 1)
        self.assertEqual(stages['{stage="chat.persist"}'], 1)
        calls = samples(text, "answerworks_provider_call_duration_seconds_count")
        self.assertTrue(any('operation="complete"' in k for k in calls))
        tokens = samples(text, "answerworks_tokens_total")
        self.assertGreater(sum(v for k, v in tokens.items() if 'direction="input"' in k), 0)
        self.assertGreater(sum(v for k, v in tokens.items() if 'direction="output"' in k), 0)

    def test_buckets_are_cumulative_and_end_at_the_count(self):
        telemetry.observe("stage_duration_seconds", 0.003, stage="x")
        telemetry.observe("stage_duration_seconds", 0.3, stage="x")
        telemetry.observe("stage_duration_seconds", 1000.0, stage="x")

        text = self.scrape()

        buckets = samples(text, "answerworks_stage_duration_seconds_bucket")
        self.assertEqual(buckets['{stage="x",le="0.005"}'], 1)
        self.assertEqual(buckets['{stage="x",le="0.5"}'], 2)
        self.assertEqual(buckets['{stage="x",le="+Inf"}'], 3)
        self.assertEqual(
            samples(text, "answerworks_stage_duration_seconds_count")['{stage="x"}'], 3
        )
        total = samples(text, "answerworks_stage_duration_seconds_sum")['{stage="x"}']
        self.assertAlmostEqual(total, 1000.303)

    def test_a_streamed_answer_records_the_time_to_first_token(self):
        self.upload(self.alice, "penguins.txt", PENGUINS)

        self.chat(self.alice, "where do penguins live", use_rag=True, stream=True)

        ttft = samples(self.scrape(), "answerworks_time_to_first_token_seconds_count")
        self.assertEqual(sum(ttft.values()), 1)
        (key,) = ttft
        self.assertIn('provider="fake"', key)

    def test_unknown_paths_share_one_route_label(self):
        self.client.get("/no/such/thing/1")
        self.client.get("/no/such/thing/2")

        counts = samples(self.scrape(), "answerworks_request_duration_seconds_count")

        self.assertEqual(counts['{route="unmatched",status="4xx"}'], 2)

    def test_gauges_report_readiness_checks_and_ingest_errors(self):
        with Session(self.engine) as db:
            db.add_all(
                [
                    Corpus(name="broken", last_ingest_error="boom"),
                    Corpus(name="fine"),
                ]
            )
            db.commit()

        text = self.scrape()

        checks = samples(text, "answerworks_readiness_check")
        self.assertEqual(checks['{check="database"}'], 1)
        self.assertIn('{check="providers"}', checks)
        errors = samples(text, "answerworks_corpus_ingest_error")
        self.assertEqual(errors['{corpus="broken"}'], 1)
        self.assertEqual(errors['{corpus="fine"}'], 0)
        self.assertEqual(samples(text, "answerworks_requests_in_flight")[""], 1)  # this scrape

    def test_a_failing_check_flips_its_gauge(self):
        self.settings.env.jwt_secret = ""

        checks = samples(self.scrape(), "answerworks_readiness_check")

        self.assertEqual(checks['{check="auth"}'], 0)
        self.assertEqual(checks['{check="database"}'], 1)

    def test_nothing_in_the_output_names_a_user_or_a_prompt(self):
        self.upload(self.alice, "penguins.txt", PENGUINS)
        self.chat(self.alice, "PROMPTSECRET where", use_rag=True)

        text = self.scrape()

        self.assertNotIn("PROMPTSECRET", text)
        self.assertNotIn("alice@example.com", text)


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

    def test_histograms_count_each_observation_in_its_bucket(self):
        telemetry.observe("x", 0.005, kind="a")  # a bound belongs to its own bucket
        telemetry.observe("x", 0.006, kind="a")
        telemetry.observe("x", 500, kind="a")
        telemetry.observe("x", 1, kind="b")

        series = telemetry.snapshot()["histograms"]["x"]

        a = series[(("kind", "a"),)]
        self.assertEqual((a.counts[0], a.counts[1], a.counts[-1], a.count), (1, 1, 1, 3))
        self.assertAlmostEqual(a.total, 500.011)
        self.assertEqual(series[(("kind", "b"),)].count, 1)
        a.count = 99  # the snapshot is a copy
        self.assertEqual(telemetry.snapshot()["histograms"]["x"][(("kind", "a"),)].count, 3)

    def test_tokens_and_in_flight_requests(self):
        telemetry.tokens_used("fake", "m", 10, 4)
        telemetry.tokens_used("fake", "m", 1, 1)
        telemetry.request_started()
        telemetry.request_started()
        telemetry.request_finished()

        snapshot = telemetry.snapshot()

        self.assertEqual(snapshot["tokens"][("fake", "m", "input")], 11)
        self.assertEqual(snapshot["tokens"][("fake", "m", "output")], 5)
        self.assertEqual(snapshot["in_flight"], 1)

    def test_reset_starts_over(self):
        telemetry.request(200, 0.1)
        telemetry.reset()

        self.assertEqual(telemetry.snapshot()["requests_total"], 0)
        self.assertLess(telemetry.uptime_seconds, 5)


class TestMonitoringStatus(StatusTestCase):
    def setUp(self):
        super().setUp()
        self.monitor = self.add_user("monitor@example.com", role=Role.MONITOR)

    def status(self, user):
        return self.client.get("/monitoring/status", headers=self.as_user(user))

    def test_administrators_and_monitors_may_read_it(self):
        self.stamp()

        for user in (self.admin, self.monitor):
            with self.subTest(role=user.role):
                response = self.status(user)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["status"], "ok")

    def test_it_is_the_same_report_the_admin_endpoint_gives(self):
        self.stamp()

        monitoring = self.status(self.monitor).json()
        admin = self.client.get("/admin/status", headers=self.as_user(self.admin)).json()

        for report in (monitoring, admin):
            del report["uptime_seconds"], report["requests"]  # change from call to call
            del report["database"]["latency_ms"]
        self.assertEqual(monitoring, admin)

    def test_regular_users_and_anonymous_callers_are_refused(self):
        self.assertEqual(self.client.get("/monitoring/status").status_code, 401)
        self.assertEqual(self.status(self.alice).status_code, 403)

    def test_accounts_that_are_not_enabled_are_refused(self):
        pending = self.add_user("pending@example.com", role=Role.MONITOR, must_change_password=True)
        disabled = self.add_user("off@example.com", role=Role.MONITOR, is_active=False)

        self.assertEqual(self.status(pending).status_code, 403)
        self.assertEqual(self.status(disabled).status_code, 403)

    def test_a_monitor_is_not_an_administrator(self):
        headers = self.as_user(self.monitor)

        for path in ("/admin/status", "/admin/users"):
            with self.subTest(route=path):
                self.assertEqual(self.client.get(path, headers=headers).status_code, 403)


if __name__ == "__main__":
    unittest.main()
