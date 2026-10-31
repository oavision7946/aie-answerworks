"""Shared corpora: who can read them (admin-managed grants and a public flag) and ingestion."""

import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import REPO_ROOT
from app.core.settings import CorporaConfig, CorpusConfig
from app.db.models import Corpus, Role, User
from app.db.repositories import corpus_repo, user_repo
from app.schemas.rag import CorpusCreate, CorpusOut, CorpusUpdate, IngestResult
from app.services.rag import ingestion
from app.services.rag.context import RagContext
from app.services.rag.errors import RagError
from app.services.rag.retriever import accessible_corpus_ids
from app.services.rag.sources.base import Source
from app.services.rag.sources.filesystem import FilesystemSource

NOT_FOUND = "Corpus not found."


def _out(db: Session, corpora: list[Corpus]) -> list[CorpusOut]:
    counts = corpus_repo.document_counts(db, [c.id for c in corpora])
    return [
        CorpusOut(
            id=c.id,
            name=c.name,
            description=c.description,
            is_public=c.is_public,
            document_count=counts.get(c.id, 0),
            has_source=bool(c.source_config),
        )
        for c in corpora
    ]


def describe(db: Session, corpus: Corpus) -> CorpusOut:
    return _out(db, [corpus])[0]


def list_for(db: Session, user: User) -> list[CorpusOut]:
    """Administrators see every corpus; other users the public ones and the ones granted to them."""
    condition = None if user.role == Role.ADMIN else accessible_corpus_ids(user)
    return _out(db, corpus_repo.list_where(db, condition))


def get(db: Session, corpus_id: uuid.UUID) -> Corpus:
    corpus = corpus_repo.get(db, corpus_id)
    if corpus is None:
        raise RagError(404, NOT_FOUND)
    return corpus


def create(db: Session, admin: User, body: CorpusCreate) -> Corpus:
    if corpus_repo.get_by_name(db, body.name):
        raise RagError(409, "A corpus with this name already exists.")
    return corpus_repo.create(db, body.name, body.description, body.is_public, admin.id)


def update(db: Session, corpus_id: uuid.UUID, body: CorpusUpdate) -> Corpus:
    corpus = get(db, corpus_id)
    if body.description is not None:
        corpus.description = body.description
    if body.is_public is not None:
        corpus.is_public = body.is_public
    return corpus_repo.save(db, corpus)


def delete(db: Session, corpus_id: uuid.UUID) -> None:
    corpus_repo.delete(db, get(db, corpus_id))


def granted_users(db: Session, corpus_id: uuid.UUID) -> list[User]:
    return corpus_repo.granted_users(db, get(db, corpus_id).id)


def grant(db: Session, corpus_id: uuid.UUID, user_id: uuid.UUID) -> None:
    corpus = get(db, corpus_id)
    if user_repo.get_by_id(db, user_id) is None:
        raise RagError(404, "User not found.")
    corpus_repo.grant(db, corpus.id, user_id)


def revoke(db: Session, corpus_id: uuid.UUID, user_id: uuid.UUID) -> None:
    corpus_repo.revoke(db, get(db, corpus_id).id, user_id)


def source_for(corpus: Corpus, formats: list[str]) -> Source:
    config = corpus.source_config
    if config.get("type") != "filesystem" or not config.get("path"):
        raise RagError(422, "This corpus has no ingestion source; upload documents to it instead.")
    root = Path(config["path"])
    return FilesystemSource(root if root.is_absolute() else REPO_ROOT / root, formats)


def ingest(
    db: Session,
    ctx: RagContext,
    corpus_id: uuid.UUID,
    embedding: str | None,
    chunking: str | None,
    source: Source | None = None,
) -> IngestResult:
    """Read the corpus' source and index every file with the chosen embedding model and splitter."""
    corpus = get(db, corpus_id)
    formats = ctx.settings.rag.supported_formats
    spec = ctx.spec(embedding, chunking)
    embedder = ctx.embedder(spec)
    try:
        report = ingestion.ingest_corpus(
            db,
            corpus,
            source or source_for(corpus, formats),
            supported=formats,
            spec=spec,
            embedder=embedder,
            store=ctx.store,
        )
    except FileNotFoundError as exc:
        raise RagError(422, "The corpus source directory does not exist on the server.") from exc
    return IngestResult(
        embedding_name=spec.embedding_name,
        chunking_name=spec.chunking_name,
        indexed=report.indexed,
        failed=report.failed,
    )


def sync_configured(db: Session, config: CorporaConfig) -> dict[str, Corpus]:
    """Create or update the corpora declared in corpora.yaml (matched by name)."""
    return {c.name: _sync_one(db, c) for c in config.corpora}


def _sync_one(db: Session, config: CorpusConfig) -> Corpus:
    corpus = corpus_repo.get_by_name(db, config.name)
    source = config.source.model_dump()
    if corpus is None:
        return corpus_repo.create(db, config.name, config.description, config.public, None, source)
    corpus.description = config.description
    corpus.is_public = config.public
    corpus.source_config = source
    return corpus_repo.save(db, corpus)
