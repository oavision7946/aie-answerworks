"""Where chunk vectors live. The rest of the code depends only on this interface."""

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass

from sqlalchemy import ColumnElement
from sqlalchemy.orm import Session

from app.db.models import Chunk
from app.services.rag.index import IndexSpec


@dataclass(frozen=True)
class ScoredChunk:
    chunk: Chunk
    score: float  # cosine similarity, 1.0 = same direction


class VectorStore(ABC):
    @abstractmethod
    def add(
        self,
        db: Session,
        document_id: uuid.UUID,
        spec: IndexSpec,
        texts: list[str],
        vectors: list[list[float]],
    ) -> None:
        """Store the chunks with `spec` recorded on each. Does not commit."""

    @abstractmethod
    def delete(self, db: Session, document_id: uuid.UUID, spec: IndexSpec | None = None) -> None:
        """Remove a document's chunks for one index, or all of them. Does not commit."""

    @abstractmethod
    def has_index(self, db: Session, document_id: uuid.UUID, spec: IndexSpec) -> bool:
        """Whether the document already has chunks made with `spec`."""

    @abstractmethod
    def search(
        self,
        db: Session,
        vector: list[float],
        spec: IndexSpec,
        allowed: ColumnElement[bool],
        top_k: int,
    ) -> list[ScoredChunk]:
        """The best matches among chunks made with `spec` whose document satisfies `allowed`."""
