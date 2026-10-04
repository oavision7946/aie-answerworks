from types import SimpleNamespace

import httpx
from openai import APITimeoutError


def fake_usage(total=123, prompt=100, completion=23, cached=0):
    return SimpleNamespace(
        total_tokens=total,
        prompt_tokens=prompt,
        completion_tokens=completion,
        prompt_tokens_details=SimpleNamespace(cached_tokens=cached),
    )


def fake_response(content, usage=None):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=usage if usage is not None else fake_usage(),
    )


def stream_chunks(*parts, usage=None):
    chunks = [
        SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=p))], usage=None)
        for p in parts
    ]
    if usage is not False:
        chunks.append(SimpleNamespace(choices=[], usage=usage or fake_usage()))
    return iter(chunks)


def timeout_error():
    return APITimeoutError(
        request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    )


def sse_frames(text):
    """Parse an SSE body into a list of (event, payload) pairs."""
    import json

    frames = [frame for frame in text.split("\n\n") if frame]
    return [(frame.splitlines()[0][7:], json.loads(frame.splitlines()[1][6:])) for frame in frames]
