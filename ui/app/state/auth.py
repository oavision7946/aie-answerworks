"""Sign-in state kept in st.session_state, with a transparent one-time token refresh."""

from collections.abc import Callable
from typing import Any

import streamlit as st

from app.clients import api_client
from app.clients.api_client import AuthExpired, TokenPair
from app.state import chat as chat_state

_KEY = "auth"
_NOTICE = "auth_notice"


def is_signed_in() -> bool:
    return st.session_state.get(_KEY) is not None


def email() -> str:
    return str(st.session_state[_KEY]["email"])


def must_change_password() -> bool:
    return bool(st.session_state[_KEY]["must_change_password"])


def is_admin() -> bool:
    return bool(st.session_state[_KEY].get("role") == "admin")


def require_sign_in() -> None:
    """Views call this first: a page must never render for an anonymous session."""
    if not is_signed_in():
        st.stop()


def access_token() -> str:
    return str(st.session_state[_KEY]["access_token"])


def store(pair: TokenPair, user_email: str, role: str = "user") -> None:
    st.session_state[_KEY] = {
        "email": user_email,
        "role": role,
        "access_token": pair.access_token,
        "refresh_token": pair.refresh_token,
        "must_change_password": pair.must_change_password,
    }


def sign_in(user_email: str, password: str) -> None:
    """Raises RuntimeError with a user-safe message when the API refuses or is unreachable."""
    pair = api_client.login(user_email, password)
    try:
        role = api_client.get_me(pair.access_token).role
    except RuntimeError:
        role = "user"  # the server enforces roles; this only decides which pages are listed
    store(pair, user_email.strip().lower(), role)


def sign_out(notice: str | None = None) -> None:
    st.session_state.pop(_KEY, None)
    st.session_state["messages"] = []
    chat_state.reset()
    if notice:
        st.session_state[_NOTICE] = notice


def pop_notice() -> str | None:
    notice = st.session_state.pop(_NOTICE, None)
    return str(notice) if notice else None


def _refresh() -> bool:
    try:
        pair = api_client.refresh(st.session_state[_KEY]["refresh_token"])
    except RuntimeError:
        return False
    store(pair, email(), str(st.session_state[_KEY].get("role", "user")))
    return True


def call_authenticated[T](fn: Callable[..., T], *args: Any) -> T:
    """Call fn(*args, token=...). On an expired token refresh once; otherwise sign out and rerun."""
    try:
        return fn(*args, token=access_token())
    except AuthExpired:
        if _refresh():
            try:
                return fn(*args, token=access_token())
            except AuthExpired:
                pass
    sign_out("Your session expired. Please sign in again.")
    st.rerun()
    raise AssertionError("unreachable")  # pragma: no cover  (st.rerun never returns)
