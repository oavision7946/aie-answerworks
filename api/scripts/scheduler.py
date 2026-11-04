"""Re-ingest shared corpora on a schedule.

    cd api && uv run python -m scripts.scheduler            # keep running, check every minute
    cd api && uv run python -m scripts.scheduler --once     # one pass, for cron or a test

A corpus with `refresh_minutes` in corpora.yaml is re-ingested with the default embedding model and
splitter once that many minutes have passed since its last ingestion (manual or scheduled).
Unchanged documents are not embedded again. Run a single scheduler per database.
"""

import argparse
import logging
import signal
import threading
import uuid
from datetime import UTC, datetime, timedelta

from opentelemetry.trace import Status, StatusCode
from sqlalchemy.orm import Session

from app.core.config import load_env
from app.core.settings import get_settings
from app.core.tracing import configure_logging, init_tracing, request_context, tracer
from app.db.models import Corpus
from app.db.session import get_engine
from app.services.llm.registry import get_registry
from app.services.rag import corpus_service
from app.services.rag.context import RagContext
from app.services.rag.errors import RagError
from app.services.rag.vector_store.pgvector import PgVectorStore

logger = logging.getLogger("scheduler")


def is_due(corpus: Corpus, now: datetime) -> bool:
    if not corpus.refresh_minutes or not corpus.source_config:
        return False
    last = corpus.last_ingested_at
    if last is None:
        return True
    if last.tzinfo is None:  # SQLite hands back naive timestamps
        last = last.replace(tzinfo=UTC)
    return now - last >= timedelta(minutes=corpus.refresh_minutes)


def run_due(db: Session, ctx: RagContext, now: datetime | None = None) -> list[str]:
    """Ingest every configured corpus that is due. Returns the names that were attempted."""
    now = now or datetime.now(UTC)
    attempted = []
    for name, corpus in corpus_service.sync_configured(db, ctx.settings.corpora).items():
        if not is_due(corpus, now):
            continue
        attempted.append(name)
        with tracer().start_as_current_span("scheduler.ingest_corpus") as span:
            span.set_attribute("answerworks.corpus", name)
            try:
                result = corpus_service.ingest(db, ctx, corpus.id, None, None)
            except RagError as exc:
                span.set_status(Status(StatusCode.ERROR))
                logger.error("Scheduled ingestion of %s failed: %s", name, exc.detail)
                corpus_service.record_failure(db, corpus, exc.detail)
                continue
        logger.info(
            "Scheduled ingestion of %s: %d indexed, %d failed",
            name,
            len(result.indexed),
            len(result.failed),
        )
    return attempted


def run_pass(ctx: RagContext) -> list[str]:
    """One scheduler pass as a single trace. Its id doubles as the request id in the logs."""
    with (
        request_context(f"scheduler-{uuid.uuid4().hex[:12]}"),
        tracer().start_as_current_span("scheduler.run") as span,
        Session(get_engine()) as db,
    ):
        attempted = run_due(db, ctx)
        span.set_attribute("answerworks.corpora_attempted", len(attempted))
        return attempted


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Re-ingest shared corpora when they are due.")
    parser.add_argument("--once", action="store_true", help="one pass, then exit")
    parser.add_argument("--poll-seconds", type=float, default=60.0, help="time between passes")
    args = parser.parse_args(argv)

    configure_logging("INFO")
    init_tracing("answerworks-scheduler")
    load_env()
    ctx = RagContext(get_settings(), get_registry(), PgVectorStore())
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    while not stop.is_set():
        try:
            run_pass(ctx)
        except Exception:  # keep the loop alive; the next pass retries
            logger.exception("Scheduled ingestion pass failed")
        if args.once:
            break
        stop.wait(args.poll_seconds)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
