"""The only module that talks to the AnswerWorks API."""

import json
from collections.abc import Callable
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from app import config


class AuthExpired(RuntimeError):
    """The API rejected the access token (missing, expired or revoked)."""


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    must_change_password: bool = False


class AskResponse(BaseModel):
    answer: str
    provider: str = ""
    model: str
    tokens_used: int
    cost_usd: float | None = None  # None when the model has no pricing configured


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


def _headers(token: str | None) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"} if token else {}


def _post_auth(path: str, json_body: dict[str, str], token: str | None = None) -> httpx.Response:
    try:
        return httpx.post(
            _url(path),
            json=json_body,
            headers=_headers(token),
            timeout=config.MODELS_TIMEOUT_SECONDS,
        )
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
        response = httpx.get(
            _url("/models"), headers=_headers(token), timeout=config.MODELS_TIMEOUT_SECONDS
        )
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
    response = httpx.post(
        _url("/ask"),
        json=_payload(question, model, force_bad_first_response),
        headers=_headers(token),
        timeout=config.ASK_TIMEOUT_SECONDS,
    )
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
    with httpx.stream(
        "POST",
        _url(path),
        json={**payload, "stream": True},
        headers=_headers(token),
        timeout=config.ASK_TIMEOUT_SECONDS,
    ) as response:
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
    method: str, path: str, token: str | None, json_body: dict[str, Any] | None = None
) -> httpx.Response:
    """One authenticated JSON call. 401 -> AuthExpired, other errors -> RuntimeError(detail)."""
    try:
        response = httpx.request(
            method,
            _url(path),
            json=json_body,
            headers=_headers(token),
            timeout=config.ASK_TIMEOUT_SECONDS,
        )
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


def _chat_payload(message: str, model: ModelInfo, conversation_id: str | None) -> dict[str, Any]:
    payload: dict[str, Any] = {"message": message, "model": model.id}
    if model.provider:
        payload["provider"] = model.provider
    if conversation_id:
        payload["conversation_id"] = conversation_id
    return payload


def chat(
    message: str, model: ModelInfo, conversation_id: str | None, token: str | None = None
) -> ChatResponse:
    response = _send("POST", "/chat", token, _chat_payload(message, model, conversation_id))
    return _parse(response, ChatResponse)


def chat_streaming(
    message: str,
    model: ModelInfo,
    conversation_id: str | None,
    render_answer: Callable[[str], Any],
    token: str | None = None,
) -> ChatResponse:
    payload = _chat_payload(message, model, conversation_id)
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
