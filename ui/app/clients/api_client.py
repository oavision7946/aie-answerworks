"""The only module that talks to the AnswerWorks API."""

import json
from collections.abc import Callable
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from app import config, tracing


class AuthExpired(RuntimeError):
    """The API rejected the access token (missing, expired or revoked)."""


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    must_change_password: bool = False


class Citation(BaseModel):
    """A passage an answer is based on, and how it was indexed."""

    chunk_id: str
    document_id: str
    filename: str
    chunk_index: int = 0
    text: str = ""
    score: float | None = None
    embedding_name: str = ""
    chunking_name: str = ""


class AskResponse(BaseModel):
    answer: str
    provider: str = ""
    model: str
    tokens_used: int
    cost_usd: float | None = None  # None when the model has no pricing configured
    citations: list[Citation] = []  # passages the answer was grounded in (chat with documents)


class ChatResponse(AskResponse):
    conversation_id: str
    message_id: str


class MessageInfo(BaseModel):
    id: str
    role: str
    content: str
    provider: str | None = None
    model: str | None = None
    tokens_used: int | None = None
    cost_usd: float | None = None
    citations: list[Citation] = []


class ConversationInfo(BaseModel):
    id: str
    title: str
    provider: str | None = None
    model: str | None = None
    updated_at: str = ""


class ConversationDetail(ConversationInfo):
    messages: list[MessageInfo] = []


class UserInfo(BaseModel):
    id: str
    email: str
    role: str
    is_active: bool = True
    must_change_password: bool = False


class IndexInfo(BaseModel):
    """One way a document was indexed: embedding model, splitter and the number of chunks."""

    embedding_name: str
    embedding_model: str
    embedding_dimensions: int
    chunking_name: str
    chunking_method: str
    chunk_size: int
    chunk_overlap: int
    chunk_count: int


class DocumentInfo(BaseModel):
    id: str
    filename: str
    size_bytes: int = 0
    status: str = "ready"
    error: str | None = None
    corpus_id: str | None = None
    indexes: list[IndexInfo] = []


class ChunkInfo(BaseModel):
    id: str
    chunk_index: int
    text: str
    embedding_name: str
    embedding_model: str
    embedding_dimensions: int
    chunking_name: str
    chunking_method: str
    chunk_size: int
    chunk_overlap: int


class CorpusInfo(BaseModel):
    id: str
    name: str
    description: str = ""
    is_public: bool = False
    document_count: int = 0
    has_source: bool = False
    source_type: str | None = None
    refresh_minutes: int | None = None
    last_ingested_at: str | None = None
    last_ingest_error: str | None = None


class EmbeddingOption(BaseModel):
    name: str
    provider: str
    model: str
    dimensions: int
    available: bool = True

    @property
    def display(self) -> str:
        return f"{self.name} · {self.model} ({self.dimensions}d)"


class ChunkingOption(BaseModel):
    name: str
    method: str
    size: int
    overlap: int

    @property
    def display(self) -> str:
        return f"{self.name} · {self.method} {self.size}/{self.overlap}"


class RagOptions(BaseModel):
    embedding_models: list[EmbeddingOption]
    chunking_strategies: list[ChunkingOption]
    default_embedding: str
    default_chunking: str
    supported_formats: list[str] = []
    max_upload_mb: int = 10


class IngestResult(BaseModel):
    embedding_name: str
    chunking_name: str
    indexed: list[str] = []
    failed: dict[str, str] = {}


class RagChoice(BaseModel):
    """What the Chat page asks the API to retrieve from."""

    embedding: str | None = None
    chunking: str | None = None
    corpus_ids: list[str] | None = None  # None = every corpus the user can read


class ModelInfo(BaseModel):
    provider: str
    id: str
    label: str

    @property
    def key(self) -> str:
        return f"{self.provider}/{self.id}" if self.provider else self.id

    @property
    def display(self) -> str:
        return f"{self.label} · {self.provider}" if self.provider else self.label


class ModelsResponse(BaseModel):
    default_provider: str | None = None
    default_model: str | None = None
    models: list[ModelInfo]


def _url(path: str) -> str:
    return f"{config.API_BASE_URL.rstrip('/')}{path}"


def fallback_model() -> ModelInfo:
    return ModelInfo(provider="", id=config.FALLBACK_MODEL, label=config.FALLBACK_MODEL)


tracing.init_tracing()


def _headers(token: str | None) -> dict[str, str]:
    """Request headers: the token, and the trace context of the call being made."""
    return tracing.inject({"Authorization": f"Bearer {token}"} if token else {})


def _post_auth(path: str, json_body: dict[str, str], token: str | None = None) -> httpx.Response:
    try:
        with tracing.client_span("POST", path) as span:
            response = httpx.post(
                _url(path),
                json=json_body,
                headers=_headers(token),
                timeout=config.MODELS_TIMEOUT_SECONDS,
            )
            tracing.record_status(span, response.status_code)
            return response
    except httpx.HTTPError as exc:
        raise RuntimeError("Could not reach the API. Is it running?") from exc


def _token_pair(response: httpx.Response) -> TokenPair:
    if response.is_error:
        raise RuntimeError(str(_error_detail(response)))
    try:
        return TokenPair.model_validate(response.json())
    except (ValueError, ValidationError) as exc:
        raise RuntimeError("The API returned an unexpected response.") from exc


def login(email: str, password: str) -> TokenPair:
    return _token_pair(_post_auth("/auth/login", {"email": email, "password": password}))


def refresh(refresh_token: str) -> TokenPair:
    return _token_pair(_post_auth("/auth/refresh", {"refresh_token": refresh_token}))


def change_password(current_password: str, new_password: str, token: str) -> None:
    response = _post_auth(
        "/auth/change-password",
        {"current_password": current_password, "new_password": new_password},
        token,
    )
    if response.status_code == 401:
        raise AuthExpired("Your session expired. Please sign in again.")
    if response.is_error:
        raise RuntimeError(str(_error_detail(response)))


def get_models(token: str | None = None) -> ModelsResponse:
    """The API's models, or a single fallback entry when the API cannot be reached."""
    try:
        with tracing.client_span("GET", "/models") as span:
            response = httpx.get(
                _url("/models"), headers=_headers(token), timeout=config.MODELS_TIMEOUT_SECONDS
            )
            tracing.record_status(span, response.status_code)
        if response.status_code == 401:
            raise AuthExpired("Your session expired. Please sign in again.")
        response.raise_for_status()
        return ModelsResponse.model_validate(response.json())
    except (httpx.HTTPError, ValidationError, ValueError):
        return ModelsResponse(models=[fallback_model()])


def _payload(question: str, model: ModelInfo, force_bad_first_response: bool) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "question": question,
        "model": model.id,
        "force_bad_first_response": force_bad_first_response,
    }
    if model.provider:
        payload["provider"] = model.provider
    return payload


def _error_detail(response: httpx.Response) -> Any:
    try:
        return response.json().get("detail", response.text)
    except ValueError:
        return response.text


def call_api(
    question: str, model: ModelInfo, force_bad_first_response: bool, token: str | None = None
) -> AskResponse:
    with tracing.client_span("POST", "/ask") as span:
        response = httpx.post(
            _url("/ask"),
            json=_payload(question, model, force_bad_first_response),
            headers=_headers(token),
            timeout=config.ASK_TIMEOUT_SECONDS,
        )
        tracing.record_status(span, response.status_code)
    if response.status_code == 401:
        raise AuthExpired("Your session expired. Please sign in again.")
    if response.is_error:
        raise RuntimeError(f"API error ({response.status_code}): {_error_detail(response)}")
    try:
        return AskResponse.model_validate(response.json())
    except (ValueError, ValidationError) as exc:
        raise RuntimeError("The API returned an unexpected response.") from exc


def _read_stream[R: BaseModel](
    path: str,
    payload: dict[str, Any],
    token: str | None,
    render_answer: Callable[[str], Any],
    result_model: type[R],
) -> R:
    """POST to a server-sent-events endpoint, rendering `delta` text and returning `done`."""
    answer = ""
    result = None
    event_type = None
    with tracing.client_span("POST", path) as span:
        with httpx.stream(
            "POST",
            _url(path),
            json={**payload, "stream": True},
            headers=_headers(token),
            timeout=config.ASK_TIMEOUT_SECONDS,
        ) as response:
            tracing.record_status(span, response.status_code)
            if response.status_code == 401:
                raise AuthExpired("Your session expired. Please sign in again.")
            if response.is_error:
                response.read()
                raise RuntimeError(f"API error ({response.status_code}): {_error_detail(response)}")
            try:
                for line in response.iter_lines():
                    if line.startswith("event: "):
                        event_type = line[7:]
                    elif line.startswith("data: "):
                        data = json.loads(line[6:])
                        if event_type == "delta":
                            answer += data["content"]
                            render_answer(answer)
                        elif event_type == "done":
                            result = result_model.model_validate(data)
                        elif event_type == "error":
                            raise RuntimeError(data.get("detail", "The streaming request failed."))
            except (ValueError, ValidationError) as exc:
                raise RuntimeError("The API returned an unexpected streaming response.") from exc
    if result is None:
        raise RuntimeError("The API stream ended before completion metadata was returned.")
    return result


def call_streaming_api(
    question: str,
    model: ModelInfo,
    force_bad_first_response: bool,
    render_answer: Callable[[str], Any],
    token: str | None = None,
) -> AskResponse:
    payload = _payload(question, model, force_bad_first_response)
    return _read_stream("/ask", payload, token, render_answer, AskResponse)


# --- accounts -----------------------------------------------------------------------------------


def _send(
    method: str,
    path: str,
    token: str | None,
    json_body: dict[str, Any] | None = None,
    *,
    files: dict[str, tuple[str, bytes]] | None = None,
    form: dict[str, str] | None = None,
) -> httpx.Response:
    """One authenticated call. 401 -> AuthExpired, other errors -> RuntimeError(detail)."""
    try:
        with tracing.client_span(method, path) as span:
            response = httpx.request(
                method,
                _url(path),
                json=json_body,
                files=files,
                data=form,
                headers=_headers(token),
                timeout=config.ASK_TIMEOUT_SECONDS,
            )
            tracing.record_status(span, response.status_code)
    except httpx.HTTPError as exc:
        raise RuntimeError("Could not reach the API. Is it running?") from exc
    if response.status_code == 401:
        raise AuthExpired("Your session expired. Please sign in again.")
    if response.is_error:
        raise RuntimeError(str(_error_detail(response)))
    return response


def _parse[R: BaseModel](response: httpx.Response, model: type[R]) -> R:
    try:
        return model.model_validate(response.json())
    except (ValueError, ValidationError) as exc:
        raise RuntimeError("The API returned an unexpected response.") from exc


def _parse_list[R: BaseModel](response: httpx.Response, model: type[R]) -> list[R]:
    try:
        return [model.model_validate(item) for item in response.json()]
    except (ValueError, TypeError, ValidationError) as exc:
        raise RuntimeError("The API returned an unexpected response.") from exc


def get_me(token: str | None = None) -> UserInfo:
    return _parse(_send("GET", "/auth/me", token), UserInfo)


# --- conversations and chat ----------------------------------------------------------------------


def _chat_payload(
    message: str, model: ModelInfo, conversation_id: str | None, rag: RagChoice | None
) -> dict[str, Any]:
    payload: dict[str, Any] = {"message": message, "model": model.id}
    if model.provider:
        payload["provider"] = model.provider
    if conversation_id:
        payload["conversation_id"] = conversation_id
    if rag is not None:
        payload["use_rag"] = True
        payload.update(rag.model_dump(exclude_none=True))  # [] keeps meaning "no shared corpora"
    return payload


def chat(
    message: str,
    model: ModelInfo,
    conversation_id: str | None,
    rag: RagChoice | None = None,
    token: str | None = None,
) -> ChatResponse:
    payload = _chat_payload(message, model, conversation_id, rag)
    return _parse(_send("POST", "/chat", token, payload), ChatResponse)


def chat_streaming(
    message: str,
    model: ModelInfo,
    conversation_id: str | None,
    render_answer: Callable[[str], Any],
    rag: RagChoice | None = None,
    token: str | None = None,
) -> ChatResponse:
    payload = _chat_payload(message, model, conversation_id, rag)
    return _read_stream("/chat", payload, token, render_answer, ChatResponse)


def list_conversations(token: str | None = None) -> list[ConversationInfo]:
    response = _send("GET", "/conversations?limit=100", token)
    return _parse_list(response, ConversationInfo)


def get_conversation(conversation_id: str, token: str | None = None) -> ConversationDetail:
    return _parse(_send("GET", f"/conversations/{conversation_id}", token), ConversationDetail)


def rename_conversation(
    conversation_id: str, title: str, token: str | None = None
) -> ConversationInfo:
    response = _send("PATCH", f"/conversations/{conversation_id}", token, {"title": title})
    return _parse(response, ConversationInfo)


def delete_conversation(conversation_id: str, token: str | None = None) -> None:
    _send("DELETE", f"/conversations/{conversation_id}", token)


# --- admin: users --------------------------------------------------------------------------------


def list_users(token: str | None = None) -> list[UserInfo]:
    return _parse_list(_send("GET", "/admin/users", token), UserInfo)


def create_user(
    email: str, temporary_password: str, role: str, token: str | None = None
) -> UserInfo:
    body = {"email": email, "temporary_password": temporary_password, "role": role}
    return _parse(_send("POST", "/admin/users", token, body), UserInfo)


def update_user(
    user_id: str, role: str | None = None, is_active: bool | None = None, token: str | None = None
) -> UserInfo:
    body = {k: v for k, v in {"role": role, "is_active": is_active}.items() if v is not None}
    return _parse(_send("PATCH", f"/admin/users/{user_id}", token, body), UserInfo)


def reset_password(user_id: str, temporary_password: str, token: str | None = None) -> UserInfo:
    body = {"temporary_password": temporary_password}
    return _parse(_send("POST", f"/admin/users/{user_id}/reset-password", token, body), UserInfo)


# --- documents and retrieval ---------------------------------------------------------------------


def get_rag_options(token: str | None = None) -> RagOptions:
    return _parse(_send("GET", "/rag/options", token), RagOptions)


def _choice(embedding: str | None, chunking: str | None) -> dict[str, str]:
    return {k: v for k, v in {"embedding": embedding, "chunking": chunking}.items() if v}


def list_documents(corpus_id: str | None = None, token: str | None = None) -> list[DocumentInfo]:
    path = "/documents" + (f"?corpus_id={corpus_id}" if corpus_id else "")
    return _parse_list(_send("GET", path, token), DocumentInfo)


def upload_document(
    filename: str,
    data: bytes,
    embedding: str | None = None,
    chunking: str | None = None,
    corpus_id: str | None = None,
    token: str | None = None,
) -> DocumentInfo:
    form = _choice(embedding, chunking)
    if corpus_id:
        form["corpus_id"] = corpus_id
    response = _send("POST", "/documents", token, files={"file": (filename, data)}, form=form)
    return _parse(response, DocumentInfo)


def index_document(
    document_id: str, embedding: str | None, chunking: str | None, token: str | None = None
) -> DocumentInfo:
    body = _choice(embedding, chunking)
    return _parse(_send("POST", f"/documents/{document_id}/index", token, body), DocumentInfo)


def list_chunks(document_id: str, limit: int = 20, token: str | None = None) -> list[ChunkInfo]:
    response = _send("GET", f"/documents/{document_id}/chunks?limit={limit}", token)
    return _parse_list(response, ChunkInfo)


def delete_document(document_id: str, token: str | None = None) -> None:
    _send("DELETE", f"/documents/{document_id}", token)


# --- corpora -------------------------------------------------------------------------------------


class DatabaseStatus(BaseModel):
    status: str
    latency_ms: float | None = None
    revision: str | None = None
    head: str | None = None
    migrated: bool = False
    pgvector: bool | None = None


class ProviderCalls(BaseModel):
    operation: str
    ok: int = 0
    error: int = 0
    average_ms: float | None = None
    last_error_at: str | None = None


class ProviderStatus(BaseModel):
    name: str
    type: str
    loaded: bool
    reason: str | None = None
    default: bool = False
    models: int = 0
    calls: list[ProviderCalls] = []


class EmbeddingStatus(BaseModel):
    name: str
    provider: str
    model: str
    dimensions: int
    available: bool


class CorpusStatus(BaseModel):
    name: str
    source_type: str | None = None
    documents: int = 0
    refresh_minutes: int | None = None
    last_ingested_at: str | None = None
    last_ingest_error: str | None = None
    overdue: bool = False


class RequestStatus(BaseModel):
    total: int = 0
    by_status: dict[str, int] = {}
    average_ms: float | None = None


class SystemStatus(BaseModel):
    status: str
    version: str
    environment: str
    uptime_seconds: float
    database: DatabaseStatus
    auth_configured: bool
    providers: list[ProviderStatus] = []
    embedding_models: list[EmbeddingStatus] = []
    corpora: list[CorpusStatus] = []
    counts: dict[str, int] = {}
    requests: RequestStatus


def get_system_status(token: str | None = None) -> SystemStatus:
    return _parse(_send("GET", "/admin/status", token), SystemStatus)


def list_corpora(token: str | None = None) -> list[CorpusInfo]:
    return _parse_list(_send("GET", "/corpora", token), CorpusInfo)


def create_corpus(
    name: str, description: str, is_public: bool, token: str | None = None
) -> CorpusInfo:
    body = {"name": name, "description": description, "is_public": is_public}
    return _parse(_send("POST", "/corpora", token, body), CorpusInfo)


def update_corpus(
    corpus_id: str, description: str, is_public: bool, token: str | None = None
) -> CorpusInfo:
    body = {"description": description, "is_public": is_public}
    return _parse(_send("PATCH", f"/corpora/{corpus_id}", token, body), CorpusInfo)


def delete_corpus(corpus_id: str, token: str | None = None) -> None:
    _send("DELETE", f"/corpora/{corpus_id}", token)


def list_corpus_access(corpus_id: str, token: str | None = None) -> list[UserInfo]:
    return _parse_list(_send("GET", f"/corpora/{corpus_id}/access", token), UserInfo)


def grant_access(corpus_id: str, user_id: str, token: str | None = None) -> None:
    _send("POST", f"/corpora/{corpus_id}/access", token, {"user_id": user_id})


def revoke_access(corpus_id: str, user_id: str, token: str | None = None) -> None:
    _send("DELETE", f"/corpora/{corpus_id}/access/{user_id}", token)


def ingest_corpus(
    corpus_id: str, embedding: str | None, chunking: str | None, token: str | None = None
) -> IngestResult:
    body = _choice(embedding, chunking)
    return _parse(_send("POST", f"/corpora/{corpus_id}/ingest", token, body), IngestResult)
