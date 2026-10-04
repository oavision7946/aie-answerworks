from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.core.config import load_model_costs
from app.schemas.ask import AskRequest, AskResponse, ModelsResponse
from app.services.llm import openai_service
from app.services.llm.streaming import stream_answer

router = APIRouter()


@router.get("/models", response_model=ModelsResponse)
def models() -> dict[str, list[str]]:
    return {"models": list(load_model_costs())}


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
def ask(request: AskRequest) -> AskResponse | StreamingResponse:
    if openai_service.client is None:
        raise HTTPException(status_code=503, detail=openai_service.NOT_CONFIGURED)
    if request.stream:
        return StreamingResponse(stream_answer(request), media_type="text/event-stream")
    try:
        return openai_service.answer_question(request)
    except openai_service.LLMServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
