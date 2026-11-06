import os

API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000")
# Export a span for each API call to an OTLP collector (OTLP over HTTP). Off by default.
TRACING_ENABLED = os.getenv("TRACING_ENABLED", "").strip().lower() in ("1", "true", "yes")
OTLP_ENDPOINT = (os.getenv("OTLP_ENDPOINT") or "http://localhost:4318").rstrip("/")  # empty = unset
# Used only when the API's /models endpoint cannot be reached.
FALLBACK_MODEL = "gpt-4o-mini"
MODELS_TIMEOUT_SECONDS = 5.0
ASK_TIMEOUT_SECONDS = 90.0
