"""What every RAG operation needs: settings, the provider registry and the vector store."""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends

from app.core.settings import Settings, get_settings
from app.services.llm.registry import ProviderRegistry, get_registry
from app.services.rag.embeddings import Embedder, build_embedder
from app.services.rag.index import IndexSpec, resolve_spec
from app.services.rag.vector_store.base import VectorStore
from app.services.rag.vector_store.pgvector import PgVectorStore


@dataclass(frozen=True)
class RagContext:
    settings: Settings
    registry: ProviderRegistry
    store: VectorStore

    def spec(self, embedding: str | None, chunking: str | None) -> IndexSpec:
        return resolve_spec(self.settings.rag, embedding, chunking)

    def embedder(self, spec: IndexSpec) -> Embedder:
        return build_embedder(self.registry, spec)


def get_rag_context(
    settings: Annotated[Settings, Depends(get_settings)],
    registry: Annotated[ProviderRegistry, Depends(get_registry)],
) -> RagContext:
    return RagContext(settings, registry, PgVectorStore())
