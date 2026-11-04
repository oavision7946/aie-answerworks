import logging
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from opentelemetry.trace import StatusCode
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core import tracing
from app.core.settings import ChunkingConfig, CorporaConfig, EmbeddingModelConfig, load_settings
from app.db.base import Base
from app.db.models import Corpus
from app.db.repositories import corpus_repo
from app.services.rag.context import RagContext
from app.services.rag.vector_store.pgvector import PgVectorStore
from scripts import scheduler
from tests.helpers import make_registry
from tests.rag_helpers import PENGUINS
from tests.tracing_helpers import exporter

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)


class TestIsDue(unittest.TestCase):
    def corpus(self, **fields):
        return Corpus(name="c", source_config={"type": "url", "urls": ["https://x.test"]}, **fields)

    def test_only_corpora_with_a_source_and_an_interval_are_ever_due(self):
        self.assertFalse(scheduler.is_due(self.corpus(), NOW))
        self.assertFalse(scheduler.is_due(Corpus(name="c", refresh_minutes=5), NOW))

    def test_never_ingested_is_due_and_otherwise_the_interval_decides(self):
        self.assertTrue(scheduler.is_due(self.corpus(refresh_minutes=60), NOW))
        recent = self.corpus(refresh_minutes=60, last_ingested_at=NOW - timedelta(minutes=59))
        self.assertFalse(scheduler.is_due(recent, NOW))
        old = self.corpus(refresh_minutes=60, last_ingested_at=NOW - timedelta(minutes=60))
        self.assertTrue(scheduler.is_due(old, NOW))

    def test_timestamps_without_a_timezone_are_read_as_utc(self):
        naive = (NOW - timedelta(minutes=5)).replace(tzinfo=None)
        self.assertFalse(
            scheduler.is_due(self.corpus(refresh_minutes=60, last_ingested_at=naive), NOW)
        )


class TestRunDue(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://", poolclass=StaticPool)
        Base.metadata.create_all(engine)
        self.engine = engine
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        (self.root / "a.txt").write_text(PENGUINS)
        settings = load_settings()
        settings.rag.embedding_models = {
            "fake-a": EmbeddingModelConfig(provider="fake", model="m", dimensions=64),
            "offline": EmbeddingModelConfig(provider="local", model="n", dimensions=8),
        }
        settings.rag.default_embedding = "fake-a"
        settings.rag.chunking_strategies = {
            "small": ChunkingConfig(method="fixed", size=40, overlap=5)
        }
        settings.rag.default_chunking = "small"
        self.settings = settings
        self.set_corpora(60, 60)
        self.ctx = RagContext(settings, make_registry(), PgVectorStore())

    def set_corpora(self, hourly, manual):
        self.settings.corpora = CorporaConfig.model_validate(
            {
                "corpora": [
                    {
                        "name": "hourly",
                        "refresh_minutes": hourly,
                        "source": {"type": "filesystem", "path": str(self.root)},
                    },
                    {
                        "name": "manual",
                        "refresh_minutes": None if manual == 60 else manual,
                        "source": {"type": "filesystem", "path": str(self.root)},
                    },
                ]
            }
        )

    def run_due(self, now):
        with Session(self.engine) as db:
            return scheduler.run_due(db, self.ctx, now)

    def info(self, name):
        with Session(self.engine) as db:
            corpus = corpus_repo.get_by_name(db, name)
            return corpus.last_ingested_at, corpus.last_ingest_error

    def test_a_due_corpus_is_ingested_once_per_interval(self):
        self.assertEqual(self.run_due(NOW), ["hourly"])
        self.assertIsNotNone(self.info("hourly")[0])
        self.assertIsNone(self.info("manual")[0])  # no interval: manual only

        later = datetime.now(UTC) + timedelta(minutes=30)
        self.assertEqual(self.run_due(later), [])
        self.assertEqual(self.run_due(datetime.now(UTC) + timedelta(minutes=61)), ["hourly"])

    def test_a_run_that_cannot_start_is_recorded_and_does_not_stop_the_others(self):
        self.settings.rag.default_embedding = "offline"  # its provider is not running
        self.set_corpora(60, 30)

        attempted = self.run_due(NOW)

        self.assertEqual(attempted, ["hourly", "manual"])
        error = self.info("hourly")[1]
        self.assertIn("not available on this server", error)

    def run_pass(self):
        with patch.object(scheduler, "get_engine", return_value=self.engine):
            return scheduler.run_pass(self.ctx)

    def test_a_pass_is_one_trace_with_a_span_per_corpus_ingested(self):
        exporter.clear()

        attempted = self.run_pass()

        spans = {s.name: s for s in exporter.get_finished_spans()}
        run, ingest = spans["scheduler.run"], spans["scheduler.ingest_corpus"]
        self.assertEqual(attempted, ["hourly"])
        self.assertIsNone(run.parent)
        self.assertEqual(ingest.parent.span_id, run.context.span_id)
        self.assertEqual(ingest.context.trace_id, run.context.trace_id)
        self.assertEqual(ingest.attributes["answerworks.corpus"], "hourly")
        self.assertEqual(run.attributes["answerworks.corpora_attempted"], 1)
        self.assertRegex(run.attributes["answerworks.request_id"], r"^scheduler-[0-9a-f]{12}$")
        self.assertEqual(tracing.current_request_id(), "-")  # the pass left no context behind

    def test_a_failed_ingestion_marks_its_span(self):
        self.settings.rag.default_embedding = "offline"
        exporter.clear()

        self.run_pass()

        ingest = next(
            s for s in exporter.get_finished_spans() if s.name == "scheduler.ingest_corpus"
        )
        self.assertEqual(ingest.status.status_code, StatusCode.ERROR)

    def test_log_lines_of_a_pass_carry_its_ids(self):
        scheduler_log = logging.getLogger("scheduler")
        correlation = tracing.CorrelationFilter()
        scheduler_log.addFilter(correlation)
        self.addCleanup(scheduler_log.removeFilter, correlation)
        exporter.clear()

        with self.assertLogs("scheduler", level="INFO") as captured:
            self.run_pass()

        run = next(s for s in exporter.get_finished_spans() if s.name == "scheduler.run")
        record = captured.records[0]
        self.assertEqual(record.request_id, run.attributes["answerworks.request_id"])
        self.assertEqual(record.trace_id, f"{run.context.trace_id:032x}")

    def test_main_runs_one_pass_with_once_and_survives_a_failing_pass(self):
        patches = (
            patch.object(scheduler, "get_settings", return_value=self.settings),
            patch.object(scheduler, "get_registry", return_value=self.ctx.registry),
            patch.object(scheduler, "get_engine", return_value=self.engine),
            patch.object(scheduler, "load_env"),
            patch.object(scheduler.signal, "signal"),  # do not change the test runner's handlers
        )
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

        self.assertEqual(scheduler.main(["--once"]), 0)
        self.assertIsNotNone(self.info("hourly")[0])

        with patch.object(scheduler, "run_due", side_effect=RuntimeError("db down")):
            with self.assertLogs("scheduler", level="ERROR"):
                self.assertEqual(scheduler.main(["--once"]), 0)

    def test_main_keeps_polling_until_stopped(self):
        waits = []
        events = []

        class StopAfterTwo:
            def __init__(self):
                self.count = 0
                events.append(self)

            def is_set(self):
                return self.count >= 2

            def wait(self, seconds):
                waits.append(seconds)
                self.count += 1

            def set(self):
                self.count = 99

        with (
            patch.object(scheduler, "get_settings", return_value=self.settings),
            patch.object(scheduler, "get_registry", return_value=self.ctx.registry),
            patch.object(scheduler, "get_engine", return_value=self.engine),
            patch.object(scheduler, "load_env"),
            patch.object(scheduler.threading, "Event", StopAfterTwo),
            patch.object(scheduler.signal, "signal") as install,
        ):
            self.assertEqual(scheduler.main(["--poll-seconds", "5"]), 0)

        self.assertEqual(waits, [5.0, 5.0])
        install.call_args.args[1]()  # the signal handler asks the loop to stop
        self.assertTrue(events[0].is_set())


if __name__ == "__main__":
    unittest.main()
