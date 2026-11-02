"""Admin: is everything working? Database, providers, embedding models, corpora and traffic."""

import streamlit as st

from app.clients import api_client
from app.clients.api_client import SystemStatus
from app.components.format import ago, duration
from app.state import auth

auth.require_sign_in()

st.markdown("## System")
st.caption(
    "A snapshot of the API: dependencies, model providers, ingestion and traffic since the API "
    "last started. The server checks that you are an administrator on every call."
)
st.button("Refresh", icon=":material/refresh:")

try:
    status: SystemStatus = auth.call_authenticated(api_client.get_system_status)
except RuntimeError as exc:
    st.error(str(exc))
    st.stop()


def mark(ok: bool) -> str:
    return ":green[ok]" if ok else ":red[needs attention]"


if status.status == "ok":
    st.success("Everything the API needs is working.")
else:
    st.warning("Something needs attention. See the sections below.")
st.caption(
    f"Version {status.version} · {status.environment} · up for {duration(status.uptime_seconds)}"
)

st.markdown("### Database")
db = status.database
columns = st.columns(4)
columns[0].markdown(f"**Connection**  \n{mark(db.status == 'ok')}")
columns[1].markdown(
    f"**Schema**  \n{mark(db.migrated)} ({db.revision or 'none'} of {db.head or '?'})"
)
columns[2].markdown(
    "**Vector search**  \n" + ("n/a" if db.pgvector is None else mark(bool(db.pgvector)))
)
columns[3].markdown(f"**Latency**  \n{db.latency_ms} ms" if db.latency_ms is not None else "—")
if not status.auth_configured:
    st.error("JWT_SECRET is not set, so nobody can sign in.")

st.markdown("### Model providers")
if not status.providers:
    st.info("No provider is enabled in providers.yaml.")
for provider in status.providers:
    title = provider.name + (" (default)" if provider.default else "")
    state = "loaded" if provider.loaded else f"not loaded: {provider.reason}"
    st.markdown(f"**{title}** · {provider.type} · {provider.models} model(s) · {state}")
    if provider.calls:
        st.dataframe(
            [
                {
                    "Operation": c.operation,
                    "Succeeded": c.ok,
                    "Failed": c.error,
                    "Average ms": c.average_ms,
                    "Last failure": ago(c.last_error_at) if c.last_error_at else "none",
                }
                for c in provider.calls
            ],
            hide_index=True,
            width="stretch",
        )

st.markdown("### Embedding models")
st.dataframe(
    [
        {
            "Name": m.name,
            "Provider": m.provider,
            "Model": m.model,
            "Dimensions": m.dimensions,
            "Available": m.available,
        }
        for m in status.embedding_models
    ],
    hide_index=True,
    width="stretch",
)

st.markdown("### Corpora")
if not status.corpora:
    st.caption("No shared corpora yet.")
else:
    st.dataframe(
        [
            {
                "Corpus": c.name,
                "Source": c.source_type or "uploads",
                "Documents": c.documents,
                "Refresh": f"every {c.refresh_minutes} min" if c.refresh_minutes else "manual",
                "Last ingested": ago(c.last_ingested_at),
                "Overdue": c.overdue,
                "Last problem": c.last_ingest_error or "",
            }
            for c in status.corpora
        ],
        hide_index=True,
        width="stretch",
    )

st.markdown("### Data and traffic")
counts = st.columns(3)
for index, (name, value) in enumerate(sorted(status.counts.items())):
    counts[index % 3].metric(name.replace("_", " ").capitalize(), value)
requests = status.requests
average = f"{requests.average_ms} ms" if requests.average_ms is not None else "n/a"
by_status = ", ".join(f"{k}: {v}" for k, v in sorted(requests.by_status.items())) or "none yet"
st.caption(f"Requests since start: {requests.total} ({by_status}) · average {average}")
