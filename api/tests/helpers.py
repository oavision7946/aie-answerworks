import json

import httpx

from app.core.settings import ModelConfig, Pricing, ProviderConfig, RequestConfig
from app.services.llm.base import Completion, Usage
from app.services.llm.providers.fake import FakeProvider
from app.services.llm.registry import ProviderRegistry

REQUEST = RequestConfig(
    timeout_seconds=20.0, max_attempts=3, retry_base_delay_seconds=0.5, max_output_tokens=256
)
PRICING = Pricing(input=1.0, cached_input=0.1, output=10.0)


def provider_config(type_="fake", **overrides):
    data = {
        "type": type_,
        "enabled": True,
        "default_model": "priced",
        "models": [
            ModelConfig(id="priced", label="Priced", pricing=PRICING),
            ModelConfig(id="free", label="Free"),
        ],
    }
    data.update(overrides)
    return ProviderConfig(**data)


def fake_provider(name="fake", **overrides) -> FakeProvider:
    return FakeProvider(name, provider_config(**overrides), REQUEST)


def make_registry(*providers: FakeProvider, default=None) -> ProviderRegistry:
    providers = providers or (fake_provider(),)
    return ProviderRegistry({p.name: p for p in providers}, default or providers[0].name, REQUEST)


def completion(text, input_tokens=100, output_tokens=23, cached=0) -> Completion:
    return Completion(text, Usage(input_tokens, cached, output_tokens))


def sse_frames(text):
    """Parse an SSE body into a list of (event, payload) pairs."""
    frames = [frame for frame in text.split("\n\n") if frame]
    return [(f.splitlines()[0][7:], json.loads(f.splitlines()[1][6:])) for f in frames]


def sse_body(*events):
    return "".join(f"event: {name}\ndata: {json.dumps(data)}\n\n" for name, data in events)


def json_response(status, payload):
    return httpx.Response(status, json=payload)
