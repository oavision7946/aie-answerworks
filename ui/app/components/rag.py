"""Pieces shared by the pages that use documents: option pickers, index summaries, sources."""

import httpx
import streamlit as st

from app.clients import api_client
from app.clients.api_client import (
    ChunkingOption,
    Citation,
    EmbeddingOption,
    IndexInfo,
    RagChoice,
    RagOptions,
)
from app.state import auth

SNIPPET = 300


def load_options() -> RagOptions | None:
    """The embedding models and splitters, or None when the API cannot provide them."""
    try:
        return auth.call_authenticated(api_client.get_rag_options)
    except (RuntimeError, httpx.HTTPError):
        return None


def pick_index(
    options: RagOptions, key: str, *, only_available: bool = True
) -> tuple[EmbeddingOption, ChunkingOption]:
    """Two selectboxes: which embedding model and which text-splitting strategy."""
    models = [m for m in options.embedding_models if m.available or not only_available]
    strategies = options.chunking_strategies
    default_model = next(
        (i for i, m in enumerate(models) if m.name == options.default_embedding), 0
    )
    default_split = next(
        (i for i, c in enumerate(strategies) if c.name == options.default_chunking), 0
    )
    model = st.selectbox(
        "Embedding model",
        models,
        index=default_model,
        format_func=lambda m: m.display,
        key=f"{key}-embedding",
        help="Vectors from different models are never compared with each other.",
    )
    strategy = st.selectbox(
        "Text splitting",
        strategies,
        index=default_split,
        format_func=lambda c: c.display,
        key=f"{key}-chunking",
        help="Method, maximum characters per chunk and characters of overlap.",
    )
    return model, strategy


def index_rows(indexes: list[IndexInfo]) -> list[dict[str, object]]:
    return [
        {
            "Embedding": i.embedding_name,
            "Model": f"{i.embedding_model} ({i.embedding_dimensions}d)",
            "Splitting": i.chunking_name,
            "Method": f"{i.chunking_method} {i.chunk_size}/{i.chunk_overlap}",
            "Chunks": i.chunk_count,
        }
        for i in indexes
    ]


def render_sources(citations: list[Citation]) -> None:
    """The passages an answer was grounded in, with how they were indexed."""
    if not citations:
        return
    with st.expander(f"Sources ({len(citations)})"):
        for number, c in enumerate(citations, 1):
            score = f" · similarity {c.score:.2f}" if c.score is not None else ""
            st.markdown(f"**[{number}] {c.filename}**{score}")
            text = c.text if len(c.text) <= SNIPPET else c.text[:SNIPPET].rstrip() + "…"
            st.caption(text)
            if c.embedding_name:
                st.caption(f"indexed with {c.embedding_name} · {c.chunking_name}")


def render_rag_controls() -> RagChoice | None:
    """Sidebar controls for the Chat page. Returns what to retrieve from, or None when off."""
    options = load_options()
    with st.sidebar:
        st.markdown('<div class="side-label">Documents</div>', unsafe_allow_html=True)
        if options is None:
            st.caption("Documents are not available right now.")
            return None
        enabled = st.toggle(
            "Answer from my documents",
            value=False,
            help="Retrieve passages from your uploads and the shared corpora you can read.",
        )
        if not enabled:
            return None
        with st.expander("Retrieval settings", expanded=False):
            model, strategy = pick_index(options, "chat")
            try:
                readable = auth.call_authenticated(api_client.list_corpora)
            except RuntimeError:
                readable = []
            chosen = [c.id for c in readable]
            if readable:
                by_id = {c.id: c.name for c in readable}
                chosen = st.multiselect(
                    "Shared corpora",
                    list(by_id),
                    default=list(by_id),
                    format_func=lambda cid: by_id[cid],
                )
        return RagChoice(
            embedding=model.name,
            chunking=strategy.name,
            corpus_ids=None if len(chosen) == len(readable) else chosen,
        )
