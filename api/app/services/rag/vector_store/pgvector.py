"""Chunks and vectors in the `chunks` table (pgvector on PostgreSQL).

On PostgreSQL the ranking runs in the database with the cosine distance operator. Other databases
(the SQLite used by unit tests) store the vector as JSON and rank in Python; results are the same.
Distances are only taken between vectors of the same length because each query filters on the
index description first.
"""

import math
import uuid

from sqlalchemy import ColumnElement, delete, select
from sqlalchemy.orm import Session

from app.db.models import Chunk, Document
from app.services.rag.index import IndexSpec
from app.services.rag.vector_store.base import ScoredChunk, VectorStore


def _matches(spec: IndexSpec) -> list[ColumnElement[bool]]:
    return [getattr(Chunk, name) == value for name, value in spec.match_fields().items()]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return sum(x * y for x, y in zip(a, b, strict=True)) / norm if norm else 0.0


class PgVectorStore(VectorStore):
    def add(
        self,
        db: Session,
        document_id: uuid.UUID,
        spec: IndexSpec,
        texts: list[str],
        vectors: list[list[float]],
    ) -> None:
        db.add_all(
            Chunk(
                document_id=document_id,
                chunk_index=index,
                text=text,
                embedding=vector,
                **spec.chunk_fields(),
            )
            for index, (text, vector) in enumerate(zip(texts, vectors, strict=True))
        )

    def delete(self, db: Session, document_id: uuid.UUID, spec: IndexSpec | None = None) -> None:
        conditions = [Chunk.document_id == document_id, *(_matches(spec) if spec else [])]
        db.execute(delete(Chunk).where(*conditions))

    def search(
        self,
        db: Session,
        vector: list[float],
        spec: IndexSpec,
        allowed: ColumnElement[bool],
        top_k: int,
    ) -> list[ScoredChunk]:
        query = select(Chunk).join(Document, Document.id == Chunk.document_id)
        query = query.where(*_matches(spec), allowed)
        if db.get_bind().dialect.name == "postgresql":  # pragma: no cover (see test_pgvector_store)
            distance = Chunk.embedding.cosine_distance(vector)
            rows = db.execute(
                query.add_columns(distance.label("distance")).order_by(distance).limit(top_k)
            )
            return [ScoredChunk(chunk, 1.0 - float(distance)) for chunk, distance in rows]
        scored = [ScoredChunk(c, cosine_similarity(vector, c.embedding)) for c in db.scalars(query)]
        scored.sort(key=lambda hit: (-hit.score, str(hit.chunk.id)))
        return scored[:top_k]
