# AnswerWorks UI

Streamlit frontend. Install with `make install-ui` (uses `uv sync --extra dev`), run from the repo
root with `make run-ui`; tests with `make test-ui`.
The UI talks to the API only through `app/clients/api_client.py`; the API address comes from
`API_BASE_URL` (default `http://127.0.0.1:8000`).

- `app/main.py` – Log Investigator chat page (model picker, streaming toggle, cost/token metadata).
- `app/components/`, `app/state/`, `app/clients/` – UI pieces, session state, API client.
- `demo_page.py` – standalone demo UI for `/ask`, kept exactly as imported (`uv run streamlit run demo_page.py`).
