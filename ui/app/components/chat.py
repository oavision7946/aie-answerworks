import streamlit as st

from app import config
from app.clients.api_client import AskResponse, get_models
from app.state.session import reset_messages


def render_sidebar() -> tuple[str, bool, bool]:
    """Draw the sidebar; return (selected_model, stream_responses, force_bad_first_response)."""
    with st.sidebar:
        st.markdown(
            """
            <div class="brand">
                <div class="brand-mark">◌</div>
                <div class="brand-name">Log Investigator</div>
                <div class="brand-copy">Evidence-led answers for distributed-system incidents.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("＋  New investigation", use_container_width=True):
            reset_messages()
            st.rerun()
        st.markdown('<div class="side-label">Connection</div>', unsafe_allow_html=True)
        st.caption(config.API_BASE_URL)
        st.markdown('<div class="side-label">Model</div>', unsafe_allow_html=True)
        model_options = get_models()
        default_index = (
            model_options.index(config.FALLBACK_MODEL)
            if config.FALLBACK_MODEL in model_options
            else 0
        )
        selected_model = st.selectbox(
            "Model", model_options, index=default_index, label_visibility="collapsed"
        )
        stream_responses = st.checkbox("Stream responses", value=False)
        with st.expander("Tests"):
            force_bad_first_response = st.checkbox(
                "Force a bad first response",
                help="The API will reject an empty first answer with Pydantic, then retry once.",
            )
        st.markdown('<div class="side-label">What to ask</div>', unsafe_allow_html=True)
        st.caption("Ask about a block, an execution trace, or evidence of an abnormal event.")
    return selected_model, stream_responses, force_bad_first_response


def render_hero() -> None:
    st.markdown(
        """
        <div class="hero">
            <div class="hero-kicker">Systems log analysis</div>
            <h1>What would you like to investigate?</h1>
            <p>Bring an HDFS trace or block identifier. I’ll look for abnormal behavior
            and explain the evidence.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_metadata(response: AskResponse) -> None:
    st.markdown(
        f"""
        <div class="metadata">
            <span>Model <strong>{response.model}</strong></span>
            <span>Tokens <strong>{response.tokens_used:,}</strong></span>
            <span>Estimated cost <strong>${response.cost_usd:.6f}</strong></span>
        </div>
        """,
        unsafe_allow_html=True,
    )
