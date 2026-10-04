import os

API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000")
# Used only when the API's /models endpoint cannot be reached.
FALLBACK_MODEL = "gpt-4o-mini"
MODELS_TIMEOUT_SECONDS = 5.0
ASK_TIMEOUT_SECONDS = 90.0
