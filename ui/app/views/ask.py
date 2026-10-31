"""Question-answer: each question is answered on its own, nothing is stored (POST /ask)."""

import httpx
import streamlit as st

from app.clients.api_client import AskResponse, call_api, call_streaming_api
from app.components.chat import render_hero, render_metadata
from app.components.models import render_model_picker
from app.state import auth
from app.state.session import init_messages, reset_messages

auth.require_sign_in()
init_messages()

with st.sidebar:
    if st.button("＋  Clear", width="stretch"):
        reset_messages()
        st.rerun()
selected_model = render_model_picker()
with st.sidebar:
    stream_responses = st.checkbox("Stream responses", value=False)
    with st.expander("Tests"):
        force_bad_first_response = st.checkbox(
            "Force a bad first response",
            help="The API will reject an empty first answer with Pydantic, then retry once.",
        )
    st.markdown('<div class="side-label">What to ask</div>', unsafe_allow_html=True)
    st.caption("One question, one answer. Nothing is saved; use Chat for conversations.")

if not st.session_state.messages:
    render_hero("Question and answer")

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if message["role"] == "assistant" and message.get("response"):
            render_metadata(AskResponse.model_validate(message["response"]))

if question := st.chat_input("Ask a question..."):
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        try:
            if stream_responses:
                answer_placeholder = st.empty()
                result = auth.call_authenticated(
                    call_streaming_api,
                    question,
                    selected_model,
                    force_bad_first_response,
                    answer_placeholder.markdown,
                )
            else:
                with st.spinner("Thinking..."):
                    result = auth.call_authenticated(
                        call_api, question, selected_model, force_bad_first_response
                    )
        except (httpx.HTTPError, RuntimeError) as exc:
            st.error(str(exc))
        else:
            if not stream_responses:
                st.markdown(result.answer)
            render_metadata(result)
            st.session_state.messages.append(
                {"role": "assistant", "content": result.answer, "response": result.model_dump()}
            )
