"""Admin: list users, create accounts, change roles, deactivate, reset passwords."""

import streamlit as st

from app.clients import api_client
from app.state import auth

auth.require_sign_in()

st.markdown("## Users")
st.caption("The server checks that you are an administrator on every call.")
notice = st.session_state.pop("users_notice", None)
if notice:
    st.success(notice)

try:
    users = auth.call_authenticated(api_client.list_users)
except RuntimeError as exc:
    st.error(str(exc))
    st.stop()

st.dataframe(
    [
        {
            "Email": u.email,
            "Role": u.role,
            "Active": u.is_active,
            "Must change password": u.must_change_password,
        }
        for u in users
    ],
    hide_index=True,
    width="stretch",
)

st.markdown("### Add a user")
with st.form("create_user", clear_on_submit=True):
    new_email = st.text_input("Email")
    temporary = st.text_input(
        "Temporary password", type="password", help="12 to 128 characters. They must change it."
    )
    new_role = st.selectbox("Role", ["user", "admin"])
    created = st.form_submit_button("Create user")
if created:
    try:
        user = auth.call_authenticated(api_client.create_user, new_email, temporary, new_role)
    except RuntimeError as exc:
        st.error(str(exc))
    else:
        st.session_state["users_notice"] = (
            f"Created {user.email}. Share the temporary password with them securely."
        )
        st.rerun()

st.markdown("### Manage a user")
by_email = {u.email: u for u in users}
chosen = by_email[st.selectbox("User", list(by_email))]
roles = ["user", "admin"]
role = st.selectbox("Role", roles, index=roles.index(chosen.role), key=f"role-{chosen.id}")
active = st.checkbox("Active", value=chosen.is_active, key=f"active-{chosen.id}")
if st.button("Save changes", key=f"save-{chosen.id}"):
    try:
        auth.call_authenticated(
            api_client.update_user,
            chosen.id,
            role if role != chosen.role else None,
            active if active != chosen.is_active else None,
        )
    except RuntimeError as exc:
        st.error(str(exc))
    else:
        st.session_state["users_notice"] = f"Updated {chosen.email}."
        st.rerun()

with st.form(f"reset-{chosen.id}", clear_on_submit=True):
    reset_value = st.text_input("New temporary password", type="password")
    reset = st.form_submit_button("Reset password")
if reset:
    try:
        auth.call_authenticated(api_client.reset_password, chosen.id, reset_value)
    except RuntimeError as exc:
        st.error(str(exc))
    else:
        st.session_state["users_notice"] = (
            f"Password reset for {chosen.email}; they must change it at next sign-in."
        )
        st.rerun()
