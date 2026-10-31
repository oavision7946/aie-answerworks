"""Chat: a conversation that is stored and remembered (POST /chat)."""

import httpx
import streamlit as st

from app.clients.api_client import AskResponse, chat, chat_streaming
from app.components.chat import render_hero, render_metadata
from app.components.models import render_model_picker
from app.state import auth
from app.state import chat as chat_state

auth.require_sign_in()
state = chat_state.get()

with st.sidebar:
    if st.button("＋  New chat", width="stretch"):
        chat_state.reset()
        st.rerun()
# Continue with the model that gave the last reply, if any.
last_reply = next((m["response"] for m in reversed(state["messages"]) if m.get("response")), None)
preferred = (last_reply["provider"] or None, last_reply["model"]) if last_reply else (None, None)
selected_model = render_model_picker(preferred)
with st.sidebar:
    stream_responses = st.checkbox("Stream responses", value=False)
    st.markdown('<div class="side-label">About this chat</div>', unsafe_allow_html=True)
    st.caption(
        "Messages are saved and the model sees the earlier ones. "
        "Find old chats under Conversations."
    )

if not state["messages"]:
    render_hero("Chat", "Your messages are saved, and the model remembers earlier ones.")
elif state["title"]:
    st.caption(f"Conversation: {state['title']}")

for message in state["messages"]:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if message.get("response"):
            render_metadata(AskResponse.model_validate(message["response"]))

if prompt := st.chat_input("Message..."):
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        try:
            if stream_responses:
                answer_placeholder = st.empty()
                result = auth.call_authenticated(
                    chat_streaming,
                    prompt,
                    selected_model,
                    chat_state.current_id(),
                    answer_placeholder.markdown,
                )
            else:
                with st.spinner("Thinking..."):
                    result = auth.call_authenticated(
                        chat, prompt, selected_model, chat_state.current_id()
                    )
        except (httpx.HTTPError, RuntimeError) as exc:
            # The API stores a message only after it is answered, so nothing was saved.
            st.error(f"{exc} Your message was not saved; send it again.")
        else:
            if not stream_responses:
                st.markdown(result.answer)
            render_metadata(result)
            state["conversation_id"] = result.conversation_id
            state["messages"].append({"role": "user", "content": prompt, "response": None})
            state["messages"].append(
                {"role": "assistant", "content": result.answer, "response": result.model_dump()}
            )
