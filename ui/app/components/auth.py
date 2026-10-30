import streamlit as st

from app.clients import api_client
from app.state import auth

MIN_PASSWORD_LENGTH = 12


def _brand() -> None:
    st.markdown(
        """
        <div class="hero">
            <div class="hero-kicker">AnswerWorks</div>
            <h1>Sign in</h1>
            <p>Accounts are created by an administrator.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_login() -> None:
    _brand()
    if notice := auth.pop_notice():
        st.info(notice)
    with st.form("login"):
        user_email = st.text_input("Email", autocomplete="username")
        password = st.text_input("Password", type="password", autocomplete="current-password")
        submitted = st.form_submit_button("Sign in", use_container_width=True)
    if submitted:
        if not user_email.strip() or not password:
            st.error("Enter your email and password.")
            return
        try:
            auth.sign_in(user_email, password)
        except RuntimeError as exc:
            st.error(str(exc))
        else:
            st.rerun()


def render_change_password() -> None:
    st.markdown(
        """
        <div class="hero">
            <div class="hero-kicker">AnswerWorks</div>
            <h1>Choose a new password</h1>
            <p>Your password was set by an administrator. Choose your own to continue.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    with st.form("change_password"):
        current = st.text_input("Current password", type="password")
        new = st.text_input(
            "New password", type="password", help=f"At least {MIN_PASSWORD_LENGTH} characters."
        )
        confirm = st.text_input("Confirm new password", type="password")
        submitted = st.form_submit_button("Change password", use_container_width=True)
    if st.button("Sign out"):
        auth.sign_out()
        st.rerun()
    if not submitted:
        return
    if len(new) < MIN_PASSWORD_LENGTH:
        st.error(f"The new password must be at least {MIN_PASSWORD_LENGTH} characters long.")
    elif new != confirm:
        st.error("The two new passwords do not match.")
    else:
        try:
            auth.call_authenticated(api_client.change_password, current, new)
            # Tokens were issued with the flag set; sign in again with the new password.
            auth.sign_in(auth.email(), new)
        except RuntimeError as exc:
            st.error(str(exc))
        else:
            st.rerun()
