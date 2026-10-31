import streamlit as st

from app.clients.api_client import AskResponse


def render_hero(kicker: str = "AI chat with RAG", blurb: str | None = None) -> None:
    blurb = blurb or (
        "Ask a question and choose the model that answers it. Answers can be grounded "
        "in your own documents."
    )
    st.markdown(
        f"""
        <div class="hero">
            <div class="hero-kicker">{kicker}</div>
            <h1>What would you like to know?</h1>
            <p>{blurb}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_metadata(response: AskResponse) -> None:
    model = f"{response.provider} / {response.model}" if response.provider else response.model
    cost = "n/a" if response.cost_usd is None else f"${response.cost_usd:.6f}"
    st.markdown(
        f"""
        <div class="metadata">
            <span>Model <strong>{model}</strong></span>
            <span>Tokens <strong>{response.tokens_used:,}</strong></span>
            <span>Estimated cost <strong>{cost}</strong></span>
        </div>
        """,
        unsafe_allow_html=True,
    )
