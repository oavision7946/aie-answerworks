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


def call_streaming_api(
    question: str,
    model: ModelInfo,
    force_bad_first_response: bool,
    render_answer: Callable[[str], Any],
    token: str | None = None,
) -> AskResponse:
    answer = ""
    result = None
    event_type = None
    with httpx.stream(
        "POST",
        _url("/ask"),
        json={**_payload(question, model, force_bad_first_response), "stream": True},
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
                        result = AskResponse.model_validate(data)
                    elif event_type == "error":
                        raise RuntimeError(data.get("detail", "The streaming request failed."))
        except (ValueError, ValidationError) as exc:
            raise RuntimeError("The API returned an unexpected streaming response.") from exc
    if result is None:
        raise RuntimeError("The API stream ended before completion metadata was returned.")
    return result
