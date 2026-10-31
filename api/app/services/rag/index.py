"""An index is one embedding model plus one splitting strategy.

Chunks store the full description (`chunk_fields`), so a stored vector can always be traced to the
model that made it and the splitter that cut its text. Retrieval only compares vectors with the
same description, which keeps vectors from different models (and different sizes) apart.
"""

from dataclasses import dataclass
from typing import Any

from app.core.settings import ChunkingConfig, RagConfig
from app.services.rag.errors import RagError


@dataclass(frozen=True)
class IndexSpec:
    embedding_name: str
    embedding_provider: str
    embedding_model: str
    embedding_dimensions: int
    chunking_name: str
    chunking_method: str
    chunk_size: int
    chunk_overlap: int

    def chunk_fields(self) -> dict[str, Any]:
        """The metadata stored on every chunk."""
        return dict(vars(self))

    def match_fields(self) -> dict[str, Any]:
        """What must be equal for two chunks to be comparable. Names are labels and may change."""
        fields = self.chunk_fields()
        return {k: v for k, v in fields.items() if k not in ("embedding_name", "chunking_name")}

    @property
    def chunking(self) -> ChunkingConfig:
        return ChunkingConfig.model_validate(
            {
                "method": self.chunking_method,
                "size": self.chunk_size,
                "overlap": self.chunk_overlap,
            }
        )


def resolve_spec(rag: RagConfig, embedding: str | None, chunking: str | None) -> IndexSpec:
    """Pick the named embedding model and splitter (the configured defaults when omitted)."""
    embedding_name = embedding or rag.default_embedding
    chunking_name = chunking or rag.default_chunking
    model = rag.embedding_models.get(embedding_name)
    strategy = rag.chunking_strategies.get(chunking_name)
    if model is None:
        raise RagError(422, f"Unknown embedding model {embedding_name!r}.")
    if strategy is None:
        raise RagError(422, f"Unknown chunking strategy {chunking_name!r}.")
    return IndexSpec(
        embedding_name=embedding_name,
        embedding_provider=model.provider,
        embedding_model=model.model,
        embedding_dimensions=model.dimensions,
        chunking_name=chunking_name,
        chunking_method=strategy.method,
        chunk_size=strategy.size,
        chunk_overlap=strategy.overlap,
    )
