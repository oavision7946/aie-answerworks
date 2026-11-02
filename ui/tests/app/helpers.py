"""Shared fixtures for the Streamlit AppTest suites."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

APP_DIR = Path(__file__).resolve().parents[2] / "app"
MAIN = str(APP_DIR / "main.py")
ASK = str(APP_DIR / "views" / "ask.py")
CHAT = str(APP_DIR / "views" / "chat.py")
CONVERSATIONS = str(APP_DIR / "views" / "conversations.py")
ADMIN_USERS = str(APP_DIR / "views" / "admin_users.py")
DOCUMENTS = str(APP_DIR / "views" / "documents.py")
ADMIN_CORPORA = str(APP_DIR / "views" / "admin_corpora.py")


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

RAG_OPTIONS = {
    "embedding_models": [
        {
            "name": "small",
            "provider": "openai",
            "model": "emb-small",
            "dimensions": 8,
            "available": True,
        },
        {
            "name": "large",
            "provider": "openai",
            "model": "emb-large",
            "dimensions": 16,
            "available": True,
        },
        {
            "name": "offline",
            "provider": "local",
            "model": "nomic",
            "dimensions": 4,
            "available": False,
        },
    ],
    "chunking_strategies": [
        {"name": "recursive", "method": "recursive", "size": 800, "overlap": 120},
        {"name": "sentence", "method": "sentence", "size": 500, "overlap": 100},
    ],
    "default_embedding": "small",
    "default_chunking": "recursive",
    "top_k": 5,
    "supported_formats": ["pdf", "txt", "md"],
    "max_upload_mb": 10,
}
INDEX = {
    "embedding_name": "small",
    "embedding_provider": "openai",
    "embedding_model": "emb-small",
    "embedding_dimensions": 8,
    "chunking_name": "recursive",
    "chunking_method": "recursive",
    "chunk_size": 800,
    "chunk_overlap": 120,
    "chunk_count": 3,
}
CORPUS = {
    "id": "k-1",
    "name": "handbook",
    "description": "Policies",
    "is_public": False,
    "document_count": 1,
    "has_source": True,
}

STATUS = {
    "status": "ok",
    "version": "0.1.0",
    "environment": "development",
    "uptime_seconds": 3725.0,
    "database": {
        "status": "ok",
        "latency_ms": 1.5,
        "revision": "0004",
        "head": "0004",
        "migrated": True,
        "pgvector": True,
    },
    "auth_configured": True,
    "providers": [
        {
            "name": "openai",
            "type": "openai",
            "loaded": True,
            "reason": None,
            "default": True,
            "models": 3,
            "calls": [
                {
                    "operation": "complete",
                    "ok": 4,
                    "error": 1,
                    "average_ms": 120.5,
                    "last_error_at": "2026-11-02T10:00:00Z",
                },
                {"operation": "embed", "ok": 2, "error": 0, "average_ms": 80.0},
            ],
        },
        {
            "name": "anthropic",
            "type": "anthropic",
            "loaded": False,
            "reason": "ANTHROPIC_API_KEY is not set",
            "default": False,
            "models": 2,
            "calls": [],
        },
    ],
    "embedding_models": [
        {"name": "small", "provider": "openai", "model": "e", "dimensions": 8, "available": True}
    ],
    "corpora": [
        {
            "name": "web",
            "source_type": "url",
            "documents": 2,
            "refresh_minutes": 60,
            "last_ingested_at": "2026-11-02T09:00:00Z",
            "last_ingest_error": "1 item(s) could not be ingested: x.",
            "overdue": True,
        },
        {"name": "manual", "documents": 0, "overdue": False},
    ],
    "counts": {"users": 3, "active_users": 2, "documents": 5},
    "requests": {"total": 40, "by_status": {"2xx": 38, "4xx": 2}, "average_ms": 12.3},
}
