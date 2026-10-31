import streamlit as st

from app import config
from app.state import auth


def render_account() -> None:
    """Sidebar block shown on every page: brand, who is signed in, sign out."""
    with st.sidebar:
        st.markdown(
            """
            <div class="brand">
                <div class="brand-mark">◌</div>
                <div class="brand-name">AnswerWorks</div>
                <div class="brand-copy">Many models, one workspace.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown('<div class="side-label">Account</div>', unsafe_allow_html=True)
        role = " (admin)" if auth.is_admin() else ""
        st.caption(f"Signed in as {auth.email()}{role}")
        if st.button("Sign out", width="stretch"):
            auth.sign_out()
            st.rerun()
        st.caption(f"API: {config.API_BASE_URL}")
