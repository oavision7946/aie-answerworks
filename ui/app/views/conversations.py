"""Browse, resume, rename and delete saved conversations."""

import streamlit as st

from app.clients import api_client
from app.state import auth
from app.state import chat as chat_state

auth.require_sign_in()

st.markdown("## Conversations")
notice = st.session_state.pop("conversations_notice", None)
if notice:
    st.success(notice)

conversations = auth.call_authenticated(api_client.list_conversations)
if not conversations:
    st.info("No saved conversations yet. Start one on the Chat page.")

pending_delete = st.session_state.get("confirm_delete")
for item in conversations:
    with st.container(border=True):
        st.markdown(f"**{item.title}**")
        model = f"{item.provider} / {item.model}" if item.model else "default model"
        st.caption(f"{model} · last activity {item.updated_at[:16].replace('T', ' ')}")
        open_col, rename_col, delete_col = st.columns([1, 1, 1])
        if open_col.button("Open", key=f"open-{item.id}", width="stretch"):
            detail = auth.call_authenticated(api_client.get_conversation, item.id)
            chat_state.open_conversation(detail)
            st.switch_page("views/chat.py")
        if delete_col.button("Delete", key=f"delete-{item.id}", width="stretch"):
            st.session_state["confirm_delete"] = item.id
            st.rerun()
        with rename_col.popover("Rename", width="stretch"):
            new_title = st.text_input("Title", value=item.title, key=f"title-{item.id}")
            if st.button("Save title", key=f"save-{item.id}"):
                try:
                    auth.call_authenticated(api_client.rename_conversation, item.id, new_title)
                except RuntimeError as exc:
                    st.error(str(exc))
                else:
                    st.rerun()
        if pending_delete == item.id:
            st.warning("Delete this conversation and all its messages?")
            yes_col, no_col = st.columns(2)
            if yes_col.button("Yes, delete", key=f"yes-{item.id}", type="primary"):
                try:
                    auth.call_authenticated(api_client.delete_conversation, item.id)
                except RuntimeError as exc:
                    st.error(str(exc))
                else:
                    if chat_state.current_id() == item.id:
                        chat_state.reset()
                    st.session_state.pop("confirm_delete", None)
                    st.session_state["conversations_notice"] = f"Deleted “{item.title}”."
                    st.rerun()
            if no_col.button("Cancel", key=f"no-{item.id}"):
                st.session_state.pop("confirm_delete", None)
                st.rerun()
