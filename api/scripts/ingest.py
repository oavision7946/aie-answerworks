"""Ingest the shared corpora declared in config/corpora.yaml.

    cd api && uv run python -m scripts.ingest --corpus company-handbook
    cd api && uv run python -m scripts.ingest --all --embedding openai-large --chunking sentence

Creates or updates each corpus from corpora.yaml, reads its source and indexes every file with the
chosen embedding model and chunking strategy (the configured defaults when omitted). Run it again
with another model or strategy to add a second index for the same documents.
"""

import argparse
import sys

from sqlalchemy.orm import Session

from app.core.config import load_env
from app.core.settings import get_settings
from app.db.session import get_engine
from app.services.llm.registry import get_registry
from app.services.rag import corpus_service
from app.services.rag.context import RagContext
from app.services.rag.errors import RagError
from app.services.rag.vector_store.pgvector import PgVectorStore


def run(
    db: Session, ctx: RagContext, names: list[str], embedding: str | None, chunking: str | None
) -> int:
    """Ingest the named corpora; returns the process exit code."""
    declared = {c.name for c in ctx.settings.corpora.corpora}
    unknown = [name for name in names if name not in declared]
    if unknown:
        print(f"Error: not defined in corpora.yaml: {', '.join(unknown)}", file=sys.stderr)
        return 1
    corpora = corpus_service.sync_configured(db, ctx.settings.corpora)
    failures = 0
    for name in names:
        try:
            result = corpus_service.ingest(db, ctx, corpora[name].id, embedding, chunking)
        except RagError as exc:
            print(f"{name}: {exc.detail}", file=sys.stderr)
            failures += 1
            continue
        print(
            f"{name}: indexed {len(result.indexed)} file(s) with "
            f"{result.embedding_name} / {result.chunking_name}"
        )
        for filename, reason in result.failed.items():
            print(f"  failed: {filename}: {reason}", file=sys.stderr)
            failures += 1
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest shared corpora into the vector store.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--corpus", action="append", help="corpus name (repeatable)")
    group.add_argument("--all", action="store_true", help="every corpus in corpora.yaml")
    parser.add_argument("--embedding", help="embedding model name from rag.yaml")
    parser.add_argument("--chunking", help="chunking strategy name from rag.yaml")
    args = parser.parse_args(argv)

    load_env()
    settings = get_settings()
    ctx = RagContext(settings, get_registry(), PgVectorStore())
    names = [c.name for c in settings.corpora.corpora] if args.all else args.corpus
    with Session(get_engine()) as db:
        return run(db, ctx, names, args.embedding, args.chunking)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
