"""Documents: your private uploads, and the shared corpora you can read."""

import streamlit as st

from app.clients import api_client
from app.clients.api_client import DocumentInfo, RagOptions
from app.components import rag
from app.state import auth

auth.require_sign_in()

st.markdown("## Documents")
st.caption("Upload files, then turn on “Answer from my documents” in Chat.")
notice = st.session_state.pop("documents_notice", None)
if notice:
    st.success(notice)

options = rag.load_options()
if options is None:
    st.error("Documents are not available right now. Is the API running?")
    st.stop()


def render_document(doc: DocumentInfo, options: RagOptions, *, manage: bool) -> None:
    size = f"{doc.size_bytes / 1024:.1f} KB"
    with st.expander(f"{doc.filename} · {size} · {doc.status}"):
        if doc.error:
            st.error(doc.error)
        if doc.indexes:
            st.markdown("**How it was indexed**")
            st.dataframe(rag.index_rows(doc.indexes), hide_index=True, width="stretch")
        if st.button("Show chunks", key=f"chunks-{doc.id}"):
            chunks = auth.call_authenticated(api_client.list_chunks, doc.id, 10)
            for c in chunks:
                st.caption(f"#{c.chunk_index} · {c.embedding_name} · {c.chunking_name}")
                st.text(c.text)
        if not manage or doc.status != "ready":
            return
        st.markdown("**Add another index**")
        model, strategy = rag.pick_index(options, f"index-{doc.id}")
        if st.button("Index with these settings", key=f"index-{doc.id}"):
            try:
                auth.call_authenticated(
                    api_client.index_document, doc.id, model.name, strategy.name
                )
            except RuntimeError as exc:
                st.error(str(exc))
            else:
                st.session_state["documents_notice"] = (
                    f"Indexed {doc.filename} with {model.name} / {strategy.name}."
                )
                st.rerun()
        if st.session_state.get("confirm_delete_document") == doc.id:
            st.warning("Delete this document and all its chunks?")
            yes_col, no_col = st.columns(2)
            if yes_col.button("Yes, delete", key=f"yes-{doc.id}", type="primary"):
                try:
                    auth.call_authenticated(api_client.delete_document, doc.id)
                except RuntimeError as exc:
                    st.error(str(exc))
                else:
                    st.session_state.pop("confirm_delete_document", None)
                    st.session_state["documents_notice"] = f"Deleted {doc.filename}."
                    st.rerun()
            if no_col.button("Cancel", key=f"no-{doc.id}"):
                st.session_state.pop("confirm_delete_document", None)
                st.rerun()
        elif st.button("Delete", key=f"delete-{doc.id}"):
            st.session_state["confirm_delete_document"] = doc.id
            st.rerun()


st.markdown("### My uploads")
st.caption("Only you can see and search these.")
with st.container(border=True):
    uploaded = st.file_uploader(
        "File", type=options.supported_formats, help=f"Up to {options.max_upload_mb} MB."
    )
    model, strategy = rag.pick_index(options, "upload")
    if st.button("Upload and index", disabled=uploaded is None, type="primary") and uploaded:
        try:
            with st.spinner("Indexing..."):
                document = auth.call_authenticated(
                    api_client.upload_document,
                    uploaded.name,
                    uploaded.getvalue(),
                    model.name,
                    strategy.name,
                )
        except RuntimeError as exc:
            st.error(str(exc))
        else:
            st.session_state["documents_notice"] = (
                f"Indexed {document.filename} with {model.name} / {strategy.name}."
            )
            st.rerun()

mine = auth.call_authenticated(api_client.list_documents, None)
if not mine:
    st.info("You have not uploaded anything yet.")
for doc in mine:
    render_document(doc, options, manage=True)

st.markdown("### Shared corpora")
st.caption("Collections shared by administrators. You can search them but not change them.")
corpora = auth.call_authenticated(api_client.list_corpora)
if not corpora:
    st.info("No shared corpora are available to you.")
else:
    by_id = {c.id: c for c in corpora}
    chosen = by_id[
        st.selectbox(
            "Corpus",
            list(by_id),
            format_func=lambda cid: f"{by_id[cid].name} · {by_id[cid].document_count} document(s)",
        )
    ]
    if chosen.description:
        st.caption(chosen.description)
    shared = auth.call_authenticated(api_client.list_documents, chosen.id)
    if not shared:
        st.info("This corpus has no documents yet.")
    for doc in shared:
        render_document(doc, options, manage=False)
