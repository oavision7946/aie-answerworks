"""Log Investigator chat page. Run with: streamlit run app/main.py"""

import httpx
import streamlit as st

from app.clients.api_client import AskResponse, call_api, call_streaming_api
from app.components.chat import render_hero, render_metadata, render_sidebar
from app.components.styles import apply_styles
from app.state.session import init_messages

st.set_page_config(
    page_title="Log Investigator",
    page_icon="◌",
    layout="centered",
    initial_sidebar_state="expanded",
)
apply_styles()
init_messages()

selected_model, stream_responses, force_bad_first_response = render_sidebar()

if not st.session_state.messages:
    render_hero()

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if message["role"] == "assistant" and message.get("response"):
            render_metadata(AskResponse.model_validate(message["response"]))

if question := st.chat_input("Ask about an incident or trace..."):
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        try:
            if stream_responses:
                answer_placeholder = st.empty()
                result = call_streaming_api(
                    question, selected_model, force_bad_first_response, answer_placeholder.markdown
                )
            else:
                with st.spinner("Reviewing the logs..."):
                    result = call_api(question, selected_model, force_bad_first_response)
        except (httpx.HTTPError, RuntimeError) as exc:
            st.error(str(exc))
        else:
            if not stream_responses:
                st.markdown(result.answer)
            render_metadata(result)
            st.session_state.messages.append(
                {"role": "assistant", "content": result.answer, "response": result.model_dump()}
            )
