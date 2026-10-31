"""Create embeddings through a provider, in batches, with the provider layer's retry rules."""

import logging

from app.core.settings import RequestConfig
from app.services.llm.base import Provider
from app.services.llm.errors import (
    FAILED,
    UNAVAILABLE,
    IncompleteResponseError,
    TransientProviderError,
)
from app.services.llm.registry import ProviderRegistry
from app.services.llm.retry import call_with_retry
from app.services.rag.errors import RagError
from app.services.rag.index import IndexSpec

logger = logging.getLogger(__name__)

BATCH_SIZE = 64


class Embedder:
    def __init__(self, provider: Provider, spec: IndexSpec, request: RequestConfig) -> None:
        self.provider = provider
        self.spec = spec
        self.request = request

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), BATCH_SIZE):
            vectors.extend(self._embed_batch(texts[start : start + BATCH_SIZE]))
        return vectors

    def _embed_batch(self, batch: list[str]) -> list[list[float]]:
        spec = self.spec
        try:
            vectors = call_with_retry(
                lambda: self.provider.embed(spec.embedding_model, batch, spec.embedding_dimensions),
                self.request,
                logger,
                f"{self.provider.name} embeddings",
            )
        except TransientProviderError as exc:
            raise RagError(503, UNAVAILABLE) from exc
        except Exception as exc:  # never leak provider details
            raise RagError(502, FAILED) from exc
        if any(len(vector) != spec.embedding_dimensions for vector in vectors):
            logger.error(
                "%s returned vectors that are not %d-dimensional; check rag.yaml",
                spec.embedding_name,
                spec.embedding_dimensions,
            )
            raise RagError(502, FAILED) from IncompleteResponseError("wrong dimensions")
        return vectors


def build_embedder(registry: ProviderRegistry, spec: IndexSpec) -> Embedder:
    provider = registry.providers.get(spec.embedding_provider)
    if provider is None:
        raise RagError(
            503, f"The embedding model {spec.embedding_name!r} is not available on this server."
        )
    return Embedder(provider, spec, registry.request)
