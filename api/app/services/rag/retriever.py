"""Retrieval and the one rule for which documents a user may see.

A document is eligible for a user when it is ready and either
  - the user owns it, or
  - it belongs to a corpus that is public or that the user has been granted.
Every query that returns document content goes through `eligible_documents`, so revoking a grant
takes effect on the next request.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import ColumnElement, and_, or_, select
from sqlalchemy.orm import Session

from app.core import tracing
from app.core.settings import RagConfig
from app.db.models import Chunk, Corpus, CorpusAccess, Document, DocumentStatus, User
from app.services.rag.embeddings import Embedder
from app.services.rag.index import IndexSpec
from app.services.rag.vector_store.base import VectorStore

SNIPPET_LENGTH = 400


def accessible_corpus_ids(user: User) -> ColumnElement[bool]:
    """Condition on `Corpus.id`: public corpora and the ones granted to `user`."""
    granted = select(CorpusAccess.corpus_id).where(CorpusAccess.user_id == user.id)
    return Corpus.id.in_(select(Corpus.id).where(or_(Corpus.is_public, Corpus.id.in_(granted))))


def eligible_documents(
    user: User, corpus_ids: Sequence[uuid.UUID] | None = None
) -> ColumnElement[bool]:
    """Condition on `Document`; `corpus_ids` narrows the shared part (own documents stay)."""
    shared = select(Corpus.id).where(accessible_corpus_ids(user))
    if corpus_ids is not None:
        shared = shared.where(Corpus.id.in_(list(corpus_ids)))
    return and_(
        Document.status == DocumentStatus.READY,
        or_(Document.owner_id == user.id, Document.corpus_id.in_(shared)),
    )


@dataclass(frozen=True)
class Hit:
    chunk: Chunk
    filename: str
    score: float | None  # None when the chunk is shown from history, not from a search


def search(
    db: Session,
    user: User,
    query: str,
    spec: IndexSpec,
    embedder: Embedder,
    store: VectorStore,
    rag: RagConfig,
    corpus_ids: Sequence[uuid.UUID] | None = None,
    top_k: int | None = None,
) -> list[Hit]:
    """Embed `query` with the index's model and return the best eligible chunks."""
    with tracing.span(
        "embed.query",
        **{
            "answerworks.provider": embedder.provider.name,
            "answerworks.model": spec.embedding_model,
        },
    ):
        [vector] = embedder.embed([query])
    limit = top_k or rag.retrieval.top_k
    with tracing.span(
        "vector.search",
        **{"db.system": db.get_bind().dialect.name, "answerworks.top_k": limit},
    ) as current:
        scored = store.search(db, vector, spec, eligible_documents(user, corpus_ids), limit)
        current.set_attribute("answerworks.rows", len(scored))
    return [
        Hit(s.chunk, s.chunk.document.filename, s.score)
        for s in scored
        if s.score >= rag.retrieval.min_score
    ]


def cited(db: Session, user: User, chunk_ids: Sequence[str]) -> list[Hit]:
    """The chunks behind an earlier answer that the user can still see, in the original order."""
    ids = []
    for value in chunk_ids:
        try:
            ids.append(uuid.UUID(value))
        except ValueError:
            continue
    if not ids:
        return []
    query = (
        select(Chunk)
        .join(Document, Document.id == Chunk.document_id)
        .where(Chunk.id.in_(ids), eligible_documents(user))
    )
    found = {chunk.id: chunk for chunk in db.scalars(query)}
    return [Hit(found[i], found[i].document.filename, None) for i in ids if i in found]


def build_context(hits: list[Hit]) -> str:
    """The numbered excerpts that are placed in front of the question."""
    return "\n\n".join(f"[{n}] ({hit.filename})\n{hit.chunk.text}" for n, hit in enumerate(hits, 1))


def grounded_question(question: str, hits: list[Hit]) -> str:
    return (
        "Answer the question using the numbered excerpts below. Cite the excerpts you rely on "
        "as [1], [2], ... If they do not contain the answer, say so.\n\n"
        f"Excerpts:\n{build_context(hits)}\n\nQuestion: {question}"
    )
