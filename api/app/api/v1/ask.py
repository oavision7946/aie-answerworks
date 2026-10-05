from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.schemas.ask import AskRequest, AskResponse, ModelsResponse
from app.services.llm import service
from app.services.llm.errors import LLMServiceError
from app.services.llm.registry import ProviderRegistry, get_registry

router = APIRouter()
Registry = Annotated[ProviderRegistry, Depends(get_registry)]


@router.get("/models", response_model=ModelsResponse)
def models(registry: Registry) -> ModelsResponse:
    default = registry.default_model()
    return ModelsResponse(
        default_provider=default.provider if default else None,
        default_model=default.id if default else None,
        models=registry.models(),
    )


@router.get("/ask", include_in_schema=False)
def ask_requires_post() -> None:
    raise HTTPException(
        status_code=405,
        detail=(
            "/ask accepts POST requests with a JSON body. "
            "Use the chat app or open /docs to submit a question."
        ),
        headers={"Allow": "POST"},
    )


@router.post("/ask", response_model=AskResponse)
def ask(request: AskRequest, registry: Registry) -> AskResponse | StreamingResponse:
    try:
        resolved = registry.resolve(request.provider, request.model)
        if request.stream:
            return StreamingResponse(
                service.stream_answer(request, resolved), media_type="text/event-stream"
            )
        return service.answer_question(request, resolved)
    except LLMServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
