import streamlit as st


def init_messages() -> None:
    if "messages" not in st.session_state:
        st.session_state.messages = []


def reset_messages() -> None:
    st.session_state.messages = []
