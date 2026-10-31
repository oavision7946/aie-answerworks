from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.permissions import active_user
from app.db.models import User
from app.db.session import get_session
from app.schemas.rag import (
    ChunkingOption,
    EmbeddingOption,
    RagOptions,
    SearchRequest,
    SearchResponse,
)
from app.services.rag import retrieval_service
from app.services.rag.context import RagContext, get_rag_context
from app.services.rag.errors import RagError

router = APIRouter(prefix="/rag", tags=["rag"])
Context = Annotated[RagContext, Depends(get_rag_context)]


@router.get("/options", response_model=RagOptions)
def options(user: Annotated[User, Depends(active_user)], ctx: Context) -> RagOptions:
    """The embedding models and chunking strategies that can be chosen, and the defaults."""
    rag = ctx.settings.rag
    return RagOptions(
        embedding_models=[
            EmbeddingOption(
                name=name,
                provider=m.provider,
                model=m.model,
                dimensions=m.dimensions,
                available=m.provider in ctx.registry.providers,
            )
            for name, m in rag.embedding_models.items()
        ],
        chunking_strategies=[
            ChunkingOption(name=name, method=c.method, size=c.size, overlap=c.overlap)
            for name, c in rag.chunking_strategies.items()
        ],
        default_embedding=rag.default_embedding,
        default_chunking=rag.default_chunking,
        top_k=rag.retrieval.top_k,
        supported_formats=rag.supported_formats,
        max_upload_mb=ctx.settings.app.limits.max_upload_mb,
    )


@router.post("/search", response_model=SearchResponse)
def search(
    body: SearchRequest,
    db: Annotated[Session, Depends(get_session)],
    user: Annotated[User, Depends(active_user)],
    ctx: Context,
) -> SearchResponse:
    """Retrieve passages without asking a model. Only chunks made with the chosen model and
    splitter are compared, among the documents you may read."""
    try:
        return retrieval_service.search(db, user, ctx, body)
    except RagError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc
