"""AnswerWorks entry point: sign-in gate, then page navigation. Run: streamlit run app/main.py"""

import streamlit as st

from app.components.account import render_account
from app.components.auth import render_change_password, render_login
from app.components.styles import apply_styles
from app.navigation import visible_pages
from app.state import auth
from app.state.session import init_messages

st.set_page_config(
    page_title="AnswerWorks",
    page_icon="◌",
    layout="centered",
    initial_sidebar_state="expanded",
)
apply_styles()
init_messages()

if not auth.is_signed_in():
    render_login()
    st.stop()
if auth.must_change_password():
    render_change_password()
    st.stop()

pages = [
    st.Page(spec.path, title=spec.title, icon=spec.icon, default=spec.default)
    for spec in visible_pages(auth.is_admin())
]
current = st.navigation(pages)
render_account()
current.run()
