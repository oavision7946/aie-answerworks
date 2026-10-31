"""The open chat conversation: its id, title and the messages shown on the Chat page."""

from typing import Any

import streamlit as st

from app.clients.api_client import ConversationDetail

_KEY = "chat"


def _fresh() -> dict[str, Any]:
    return {"conversation_id": None, "title": None, "messages": []}


def get() -> dict[str, Any]:
    if _KEY not in st.session_state:
        st.session_state[_KEY] = _fresh()
    state: dict[str, Any] = st.session_state[_KEY]
    return state


def reset() -> None:
    st.session_state[_KEY] = _fresh()


def open_conversation(detail: ConversationDetail) -> None:
    """Load a stored conversation so the Chat page continues it."""
    st.session_state[_KEY] = {
        "conversation_id": detail.id,
        "title": detail.title,
        "messages": [
            {
                "role": m.role,
                "content": m.content,
                "response": (
                    {
                        "answer": m.content,
                        "provider": m.provider or "",
                        "model": m.model or "",
                        "tokens_used": m.tokens_used or 0,
                        "cost_usd": m.cost_usd,
                    }
                    if m.role == "assistant" and m.model
                    else None
                ),
            }
            for m in detail.messages
        ],
    }


def current_id() -> str | None:
    value = get()["conversation_id"]
    return str(value) if value else None
