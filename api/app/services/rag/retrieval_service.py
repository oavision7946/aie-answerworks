"""Retrieval for the API: pick the index, run the search, describe the hits."""

import uuid
from collections.abc import Sequence

from sqlalchemy.orm import Session

from app.core import tracing
from app.db.models import User
from app.schemas.rag import Citation, SearchRequest, SearchResponse
from app.services.rag import retriever
from app.services.rag.context import RagContext
from app.services.rag.retriever import SNIPPET_LENGTH, Hit


def citation(hit: Hit) -> Citation:
    chunk = hit.chunk
    return Citation(
        chunk_id=chunk.id,
        document_id=chunk.document_id,
        filename=hit.filename,
        chunk_index=chunk.chunk_index,
        text=chunk.text[:SNIPPET_LENGTH],
        score=None if hit.score is None else round(hit.score, 4),
        embedding_name=chunk.embedding_name,
        chunking_name=chunk.chunking_name,
    )


def retrieve(
    db: Session,
    user: User,
    ctx: RagContext,
    query: str,
    embedding: str | None,
    chunking: str | None,
    corpus_ids: Sequence[uuid.UUID] | None = None,
    top_k: int | None = None,
) -> list[Hit]:
    spec = ctx.spec(embedding, chunking)
    with tracing.span(
        "rag.retrieve",
        **{
            "answerworks.embedding": spec.embedding_name,
            "answerworks.chunking": spec.chunking_name,
            "answerworks.top_k": top_k or ctx.settings.rag.retrieval.top_k,
            "answerworks.corpora": len(corpus_ids) if corpus_ids else None,
        },
    ) as current:
        hits = retriever.search(
            db,
            user,
            query,
            spec,
            ctx.embedder(spec),
            ctx.store,
            ctx.settings.rag,
            corpus_ids,
            top_k,
        )
        current.set_attribute("answerworks.hits", len(hits))
        return hits


def search(db: Session, user: User, ctx: RagContext, body: SearchRequest) -> SearchResponse:
    spec = ctx.spec(body.embedding, body.chunking)
    hits = retrieve(
        db, user, ctx, body.query, body.embedding, body.chunking, body.corpus_ids, body.top_k
    )
    return SearchResponse(
        embedding_name=spec.embedding_name,
        chunking_name=spec.chunking_name,
        hits=[citation(hit) for hit in hits],
    )
