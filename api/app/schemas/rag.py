import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, field_validator

from app.db.models import DocumentStatus


def _strip(value: Any) -> Any:
    return value.strip() if isinstance(value, str) else value


class IndexInfo(BaseModel):
    """How a document's chunks were made: the embedding model and the splitter, plus the count."""

    model_config = ConfigDict(from_attributes=True)

    embedding_name: str
    embedding_provider: str
    embedding_model: str
    embedding_dimensions: int
    chunking_name: str
    chunking_method: str
    chunk_size: int
    chunk_overlap: int
    chunk_count: int


class DocumentOut(BaseModel):
    id: uuid.UUID
    filename: str
    size_bytes: int
    status: DocumentStatus
    error: str | None
    owner_id: uuid.UUID | None
    corpus_id: uuid.UUID | None
    created_at: datetime
    indexes: list[IndexInfo]


class ChunkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    chunk_index: int
    text: str
    embedding_name: str
    embedding_provider: str
    embedding_model: str
    embedding_dimensions: int
    chunking_name: str
    chunking_method: str
    chunk_size: int
    chunk_overlap: int


class IndexRequest(BaseModel):
    """Which embedding model and splitter to use; omitted fields take the configured defaults."""

    model_config = ConfigDict(extra="forbid")

    embedding: StrictStr | None = None
    chunking: StrictStr | None = None


class Citation(BaseModel):
    """A passage an answer (or a search) is based on, with how it was indexed."""

    chunk_id: uuid.UUID
    document_id: uuid.UUID
    filename: str
    chunk_index: int
    text: str
    score: float | None  # cosine similarity; null when shown from history
    embedding_name: str
    chunking_name: str


class SearchRequest(IndexRequest):
    query: StrictStr = Field(min_length=1, max_length=2000)
    corpus_ids: list[uuid.UUID] | None = None
    top_k: StrictInt | None = Field(default=None, ge=1, le=50)

    @field_validator("query", mode="before")
    @classmethod
    def strip_query(cls, value: Any) -> Any:
        return _strip(value)


class SearchResponse(BaseModel):
    embedding_name: str
    chunking_name: str
    hits: list[Citation]


class EmbeddingOption(BaseModel):
    name: str
    provider: str
    model: str
    dimensions: int
    available: bool  # false when its provider is not running on this server


class ChunkingOption(BaseModel):
    name: str
    method: str
    size: int
    overlap: int


class RagOptions(BaseModel):
    embedding_models: list[EmbeddingOption]
    chunking_strategies: list[ChunkingOption]
    default_embedding: str
    default_chunking: str
    top_k: int
    supported_formats: list[str]
    max_upload_mb: int


class CorpusOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str
    is_public: bool
    document_count: int
    has_source: bool  # an ingestion source is configured


class CorpusCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: StrictStr = Field(min_length=1, max_length=100)
    description: StrictStr = Field(default="", max_length=1000)
    is_public: StrictBool = False

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, value: Any) -> Any:
        return _strip(value)


class CorpusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: StrictStr | None = Field(default=None, max_length=1000)
    is_public: StrictBool | None = None


class AccessGrant(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: uuid.UUID


class IngestResult(BaseModel):
    embedding_name: str
    chunking_name: str
    indexed: list[str]
    failed: dict[str, str]
