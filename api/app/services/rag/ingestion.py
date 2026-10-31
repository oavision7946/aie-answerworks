"""parse -> split -> embed -> store, for one file or for every file a corpus source offers."""

import logging
import uuid
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.db.models import Corpus, Document, DocumentStatus
from app.db.repositories import document_repo
from app.services.rag.chunking import split_text
from app.services.rag.embeddings import Embedder
from app.services.rag.errors import RagError
from app.services.rag.index import IndexSpec
from app.services.rag.parsers import ParseError, parse
from app.services.rag.sources.base import Source
from app.services.rag.vector_store.base import VectorStore

logger = logging.getLogger(__name__)


def index_document(
    db: Session, document: Document, spec: IndexSpec, embedder: Embedder, store: VectorStore
) -> int:
    """Index `document.text` with `spec`, replacing chunks made earlier with the same index.

    Chunks made with other embedding models or splitters are left alone. Returns the chunk count.
    """
    texts = split_text(document.text, spec.chunking)
    vectors = embedder.embed(texts)
    store.delete(db, document.id, spec)
    store.add(db, document.id, spec, texts, vectors)
    db.commit()
    return len(texts)


def ingest_file(
    db: Session,
    *,
    filename: str,
    data: bytes,
    owner_id: uuid.UUID | None,
    corpus_id: uuid.UUID | None,
    supported: list[str],
    spec: IndexSpec,
    embedder: Embedder,
    store: VectorStore,
) -> Document:
    """Create or refresh one document and index it. Raises ParseError or RagError on failure."""
    text = parse(filename, data, supported)
    existing = document_repo.get_in_corpus(db, corpus_id, filename) if corpus_id else None
    document = existing or Document(owner_id=owner_id, corpus_id=corpus_id, filename=filename)
    changed = existing is not None and existing.text != text
    document.text = text
    document.size_bytes = len(data)
    document.status = DocumentStatus.READY
    document.error = None
    if changed:
        store.delete(db, document.id)  # the text changed, so every older index is stale
    document_repo.save(db, document)
    try:
        index_document(db, document, spec, embedder, store)
    except Exception:
        db.rollback()
        if existing is None:
            document_repo.delete(db, document)
        raise
    return document


@dataclass
class IngestReport:
    indexed: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)


def ingest_corpus(
    db: Session,
    corpus: Corpus,
    source: Source,
    *,
    supported: list[str],
    spec: IndexSpec,
    embedder: Embedder,
    store: VectorStore,
) -> IngestReport:
    """Ingest every file of `source` into `corpus`. A failing file is recorded, not fatal."""
    report = IngestReport()
    for file in source.files():
        try:
            ingest_file(
                db,
                filename=file.name,
                data=file.data,
                owner_id=None,
                corpus_id=corpus.id,
                supported=supported,
                spec=spec,
                embedder=embedder,
                store=store,
            )
        except (ParseError, RagError) as exc:
            message = exc.detail if isinstance(exc, RagError) else str(exc)
            logger.warning("Could not ingest %s into %s: %s", file.name, corpus.name, message)
            report.failed[file.name] = message
            _record_failure(db, corpus, file.name, len(file.data), message)
        else:
            report.indexed.append(file.name)
    return report


def _record_failure(db: Session, corpus: Corpus, filename: str, size: int, message: str) -> None:
    document = document_repo.get_in_corpus(db, corpus.id, filename)
    if document is None:
        document = Document(corpus_id=corpus.id, filename=filename, text="")
    document.size_bytes = size
    document.status = DocumentStatus.FAILED
    document.error = message
    document_repo.save(db, document)
