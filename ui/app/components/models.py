import streamlit as st

from app.clients.api_client import ModelInfo, fallback_model, get_models
from app.state import auth


def render_model_picker(preferred: tuple[str | None, str | None] = (None, None)) -> ModelInfo:
    """Sidebar model selector. `preferred` (provider, model) wins over the API's default."""
    with st.sidebar:
        st.markdown('<div class="side-label">Model</div>', unsafe_allow_html=True)
        available = auth.call_authenticated(get_models)
        models = available.models
        if not models:
            st.warning("The API has no models available. Check its provider configuration.")
            models = [fallback_model()]
        by_key = {m.key: m for m in models}
        wanted = [preferred, (available.default_provider, available.default_model)]
        default_key = next(
            (m.key for want in wanted for m in models if (m.provider, m.id) == want),
            models[0].key,
        )
        selected_key = st.selectbox(
            "Model",
            list(by_key),
            index=list(by_key).index(default_key),
            format_func=lambda key: by_key[key].display,
            label_visibility="collapsed",
        )
    return by_key[selected_key]
