"""Shared fixtures for the Streamlit AppTest suites."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

APP_DIR = Path(__file__).resolve().parents[2] / "app"
MAIN = str(APP_DIR / "main.py")
ASK = str(APP_DIR / "views" / "ask.py")
CHAT = str(APP_DIR / "views" / "chat.py")
CONVERSATIONS = str(APP_DIR / "views" / "conversations.py")
ADMIN_USERS = str(APP_DIR / "views" / "admin_users.py")


def models_payload(*models, default=0):
    """models: (provider, id, label) tuples; `default` indexes the API's default model."""
    infos = [{"provider": p, "id": i, "label": label} for p, i, label in models]
    return {
        "default_provider": infos[default]["provider"],
        "default_model": infos[default]["id"],
        "models": infos,
    }


TWO = models_payload(
    ("openai", "gpt-4o", "GPT-4o"), ("anthropic", "claude-x", "Claude X"), default=1
)
ONE = models_payload(("openai", "gpt-4o-mini", "GPT-4o mini"))
RESULT = {
    "answer": "What RAG is.",
    "provider": "openai",
    "model": "gpt-4o",
    "tokens_used": 1234,
    "latency_ms": 5,
    "cost_usd": 0.000123,
}


SIGNED_IN = {
    "email": "ana@example.com",
    "role": "user",
    "access_token": "access-1",
    "refresh_token": "refresh-1",
    "must_change_password": False,
}

ADMIN_SIGNED_IN = {**SIGNED_IN, "email": "root@example.com", "role": "admin"}


def new_app(auth=SIGNED_IN, view=MAIN) -> AppTest:
    """The whole app (sign-in gate and navigation) by default, or one view on its own."""
    at = AppTest.from_file(view, default_timeout=10)
    if auth is not None:
        at.session_state["auth"] = dict(auth)
    return at


CHAT_RESULT = {**RESULT, "conversation_id": "c-1", "message_id": "m-2"}
ME_USER = {
    "id": "u-1",
    "email": "ana@example.com",
    "role": "user",
    "is_active": True,
    "must_change_password": False,
}
ME_ADMIN = {**ME_USER, "id": "u-0", "email": "root@example.com", "role": "admin"}
