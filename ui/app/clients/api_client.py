"""The only module that talks to the AnswerWorks API."""

import json
from collections.abc import Callable
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from app import config


class AskResponse(BaseModel):
    answer: str
    model: str
    tokens_used: int
    cost_usd: float


class ModelsResponse(BaseModel):
    models: list[str]


def _url(path: str) -> str:
    return f"{config.API_BASE_URL.rstrip('/')}{path}"


def get_models() -> list[str]:
    try:
        response = httpx.get(_url("/models"), timeout=config.MODELS_TIMEOUT_SECONDS)
        response.raise_for_status()
        return ModelsResponse.model_validate(response.json()).models
    except (httpx.HTTPError, ValidationError, ValueError):
        return [config.FALLBACK_MODEL]


def _error_detail(response: httpx.Response) -> Any:
    try:
        return response.json().get("detail", response.text)
    except ValueError:
        return response.text


def call_api(question: str, model: str, force_bad_first_response: bool) -> AskResponse:
    response = httpx.post(
        _url("/ask"),
        json={
            "question": question,
            "model": model,
            "force_bad_first_response": force_bad_first_response,
        },
        timeout=config.ASK_TIMEOUT_SECONDS,
    )
    if response.is_error:
        raise RuntimeError(f"API error ({response.status_code}): {_error_detail(response)}")
    try:
        return AskResponse.model_validate(response.json())
    except (ValueError, ValidationError) as exc:
        raise RuntimeError("The API returned an unexpected response.") from exc


def call_streaming_api(
    question: str,
    model: str,
    force_bad_first_response: bool,
    render_answer: Callable[[str], Any],
) -> AskResponse:
    answer = ""
    result = None
    event_type = None
    with httpx.stream(
        "POST",
        _url("/ask"),
        json={
            "question": question,
            "model": model,
            "stream": True,
            "force_bad_first_response": force_bad_first_response,
        },
        timeout=config.ASK_TIMEOUT_SECONDS,
    ) as response:
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
