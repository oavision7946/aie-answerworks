import streamlit as st

from app import config
from app.clients.api_client import AskResponse, ModelInfo, fallback_model, get_models
from app.state.session import reset_messages


def render_sidebar() -> tuple[ModelInfo, bool, bool]:
    """Draw the sidebar; return (selected_model, stream_responses, force_bad_first_response)."""
    with st.sidebar:
        st.markdown(
            """
            <div class="brand">
                <div class="brand-mark">◌</div>
                <div class="brand-name">AnswerWorks</div>
                <div class="brand-copy">Many models, one workspace.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("＋  New chat", use_container_width=True):
            reset_messages()
            st.rerun()
        st.markdown('<div class="side-label">Connection</div>', unsafe_allow_html=True)
        st.caption(config.API_BASE_URL)
        st.markdown('<div class="side-label">Model</div>', unsafe_allow_html=True)
        available = get_models()
        models = available.models
        if not models:
            st.warning("The API has no models available. Check its provider configuration.")
            models = [fallback_model()]
        by_key = {m.key: m for m in models}
        default_key = next(
            (
                m.key
                for m in models
                if m.provider == available.default_provider and m.id == available.default_model
            ),
            models[0].key,
        )
        selected_key = st.selectbox(
            "Model",
            list(by_key),
            index=list(by_key).index(default_key),
            format_func=lambda key: by_key[key].display,
            label_visibility="collapsed",
        )
        selected_model = by_key[selected_key]
        stream_responses = st.checkbox("Stream responses", value=False)
        with st.expander("Tests"):
            force_bad_first_response = st.checkbox(
                "Force a bad first response",
                help="The API will reject an empty first answer with Pydantic, then retry once.",
            )
        st.markdown('<div class="side-label">What to ask</div>', unsafe_allow_html=True)
        st.caption("Ask anything. Pick a model and compare answers, cost and token use.")
    return selected_model, stream_responses, force_bad_first_response


def render_hero() -> None:
    st.markdown(
        """
        <div class="hero">
            <div class="hero-kicker">AI chat with RAG</div>
            <h1>What would you like to know?</h1>
            <p>Ask a question and choose the model that answers it. Answers can be grounded
            in your own documents.</p>
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
