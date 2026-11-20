"""Monitoring: a short health summary and the way into the dashboards (Grafana)."""

import streamlit as st

from app.clients import api_client
from app.clients.api_client import SystemStatus
from app.components.format import duration
from app.state import auth

auth.require_sign_in()

st.markdown("## Monitoring")
st.caption(
    "Is everything working, and where does a request spend its time? Open the dashboards for "
    "health, latency, traces and the model server's GPU. The server checks your role on every call."
)
st.button("Refresh", icon=":material/refresh:")

try:
    status: SystemStatus = auth.call_authenticated(api_client.get_monitoring_status)
except RuntimeError as exc:
    st.error(str(exc))
    st.stop()

if status.status == "ok":
    st.success("Everything the API needs is working.")
else:
    st.warning("Something needs attention.")
st.caption(
    f"Version {status.version} · {status.environment} · up for {duration(status.uptime_seconds)}"
)

loaded = sum(1 for provider in status.providers if provider.loaded)
attention = sum(1 for corpus in status.corpora if corpus.overdue or corpus.last_ingest_error)
summary = st.columns(4)
summary[0].metric("Database", "ok" if status.database.status == "ok" else "down")
summary[1].metric("Schema", "up to date" if status.database.migrated else "behind")
summary[2].metric("Providers loaded", f"{loaded} of {len(status.providers)}")
summary[3].metric("Corpora to check", attention)
requests = status.requests
st.caption(f"Requests since the API started: {requests.total}")

st.markdown("### Dashboards")
st.caption("Health, latency, request traces and GPU. They open in a new tab, read-only.")
if st.button("Open dashboards", icon=":material/dashboard:", type="primary"):
    try:
        link = auth.call_authenticated(api_client.create_dashboard_link)
    except RuntimeError as exc:
        st.info(str(exc))
    else:
        st.link_button("Go to the dashboards", link.login_url, icon=":material/open_in_new:")
        st.caption(
            f"This link works once and for {duration(link.expires_in)}. "
            "Open the dashboards again from this page whenever you need to."
        )
