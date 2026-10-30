# AnswerWorks UI

Streamlit frontend. Install with `make install-ui` (uses `uv sync --extra dev`), run from the repo
root with `make run-ui`; tests with `make test-ui`.
The UI talks to the API only through `app/clients/api_client.py`; the API address comes from
`API_BASE_URL` (default `http://127.0.0.1:8000`).

- `app/main.py` – AnswerWorks app: sign-in screen, forced password change, then the chat page (model picker across providers, streaming toggle, cost/token metadata).
- `app/components/`, `app/state/`, `app/clients/` – UI pieces, session state, API client.
- `app/state/auth.py` – tokens in `st.session_state`; refreshes an expired access token once, otherwise signs out.
- `demo_page.py` – standalone demo UI for `/ask`, kept exactly as imported. It sends no token, so the API now rejects it with 401.
