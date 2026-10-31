"""Admin: shared corpora, who can read them, and ingestion."""

import streamlit as st

from app.clients import api_client
from app.clients.api_client import CorpusInfo, RagOptions
from app.components import rag
from app.state import auth

auth.require_sign_in()

st.markdown("## Corpora")
st.caption(
    "A corpus is readable by the users you grant it to, or by everyone when it is public. "
    "The server checks that you are an administrator on every call."
)
notice = st.session_state.pop("corpora_notice", None)
if notice:
    st.success(notice)

options = rag.load_options()
try:
    corpora = auth.call_authenticated(api_client.list_corpora)
    users = auth.call_authenticated(api_client.list_users)
except RuntimeError as exc:
    st.error(str(exc))
    st.stop()
if options is None:
    st.error("Documents are not available right now. Is the API running?")
    st.stop()

with st.expander("New corpus", expanded=not corpora):
    with st.form("create_corpus", clear_on_submit=True):
        name = st.text_input("Name")
        description = st.text_input("Description")
        is_public = st.checkbox("Public (every user can read it)")
        created = st.form_submit_button("Create corpus")
    if created:
        try:
            auth.call_authenticated(api_client.create_corpus, name, description, is_public)
        except RuntimeError as exc:
            st.error(str(exc))
        else:
            st.session_state["corpora_notice"] = f"Created {name.strip()}."
            st.rerun()


def done(message: str) -> None:
    st.session_state["corpora_notice"] = message
    st.rerun()


def render_corpus(corpus: CorpusInfo, options: RagOptions) -> None:
    cid = corpus.id
    visibility = "public" if corpus.is_public else "restricted"
    with st.expander(f"{corpus.name} · {visibility} · {corpus.document_count} document(s)"):
        st.markdown("**Settings**")
        new_description = st.text_input("Description", corpus.description, key=f"desc-{cid}")
        new_public = st.checkbox("Public", corpus.is_public, key=f"public-{cid}")
        if st.button("Save settings", key=f"save-{cid}"):
            try:
                auth.call_authenticated(api_client.update_corpus, cid, new_description, new_public)
            except RuntimeError as exc:
                st.error(str(exc))
            else:
                done(f"Updated {corpus.name}.")

        st.markdown("**Who can read it**")
        granted = auth.call_authenticated(api_client.list_corpus_access, cid)
        if corpus.is_public:
            st.caption("It is public, so grants are not needed.")
        for user in granted:
            email_col, revoke_col = st.columns([3, 1])
            email_col.write(user.email)
            if revoke_col.button("Revoke", key=f"revoke-{cid}-{user.id}"):
                auth.call_authenticated(api_client.revoke_access, cid, user.id)
                done(f"{user.email} can no longer read {corpus.name}.")
        granted_ids = {u.id for u in granted}
        candidates = {u.email: u.id for u in users if u.id not in granted_ids}
        if candidates:
            who = st.selectbox("Grant access to", list(candidates), key=f"who-{cid}")
            if st.button("Grant access", key=f"grant-{cid}"):
                auth.call_authenticated(api_client.grant_access, cid, candidates[who])
                done(f"{who} can now read {corpus.name}.")

        st.markdown("**Add documents**")
        model, strategy = rag.pick_index(options, f"corpus-{cid}")
        uploaded = st.file_uploader(
            "Upload a file", type=options.supported_formats, key=f"up-{cid}"
        )
        if (
            st.button("Upload and index", key=f"upload-{cid}", disabled=uploaded is None)
            and uploaded
        ):
            try:
                auth.call_authenticated(
                    api_client.upload_document,
                    uploaded.name,
                    uploaded.getvalue(),
                    model.name,
                    strategy.name,
                    cid,
                )
            except RuntimeError as exc:
                st.error(str(exc))
            else:
                done(f"Added {uploaded.name} to {corpus.name}.")
        if corpus.has_source:
            st.caption("This corpus has a configured source folder.")
            if st.button("Ingest source folder", key=f"ingest-{cid}"):
                try:
                    with st.spinner("Ingesting..."):
                        result = auth.call_authenticated(
                            api_client.ingest_corpus, cid, model.name, strategy.name
                        )
                except RuntimeError as exc:
                    st.error(str(exc))
                else:
                    failed = "".join(f"\n- {n}: {why}" for n, why in result.failed.items())
                    done(
                        f"Indexed {len(result.indexed)} file(s) with {result.embedding_name} / "
                        f"{result.chunking_name}." + (f" Failed:{failed}" if failed else "")
                    )

        st.markdown("**Documents**")
        docs = auth.call_authenticated(api_client.list_documents, cid)
        if not docs:
            st.caption("No documents yet.")
        for doc in docs:
            name_col, delete_col = st.columns([4, 1])
            label = f"{doc.filename} · {doc.status}"
            if doc.indexes:
                label += " · " + ", ".join(
                    f"{i.embedding_name}/{i.chunking_name} ({i.chunk_count})" for i in doc.indexes
                )
            name_col.write(label + (f" — {doc.error}" if doc.error else ""))
            if delete_col.button("Delete", key=f"deldoc-{doc.id}"):
                auth.call_authenticated(api_client.delete_document, doc.id)
                done(f"Deleted {doc.filename}.")

        st.markdown("**Delete corpus**")
        if st.session_state.get("confirm_delete_corpus") == cid:
            st.warning("Delete this corpus with all its documents and chunks?")
            yes_col, no_col = st.columns(2)
            if yes_col.button("Yes, delete", key=f"yesc-{cid}", type="primary"):
                auth.call_authenticated(api_client.delete_corpus, cid)
                st.session_state.pop("confirm_delete_corpus", None)
                done(f"Deleted {corpus.name}.")
            if no_col.button("Cancel", key=f"noc-{cid}"):
                st.session_state.pop("confirm_delete_corpus", None)
                st.rerun()
        elif st.button("Delete corpus", key=f"delc-{cid}"):
            st.session_state["confirm_delete_corpus"] = cid
            st.rerun()


for corpus in corpora:
    render_corpus(corpus, options)
