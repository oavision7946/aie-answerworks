# AnswerWorks UI

Streamlit frontend. Install with `make install-ui` (uses `uv sync --extra dev`), run from the repo
root with `make run-ui`; tests with `make test-ui`.
The UI talks to the API only through `app/clients/api_client.py`; the API address comes from
`API_BASE_URL` (default `http://127.0.0.1:8000`).

## Pages

`app/main.py` shows the sign-in screen, then the forced password-change screen, then navigation
(`app/navigation.py` lists the pages and who may see them):

| Page | File | API | Notes |
|---|---|---|---|
| Chat (default) | `app/views/chat.py` | `POST /chat` | Stored conversation; model picker, streaming toggle, usage under each answer |
| Conversations | `app/views/conversations.py` | `/conversations` | Open (resume in Chat), rename, delete with confirmation |
| Ask | `app/views/ask.py` | `POST /ask` | One-off question-answer, nothing stored |
| Admin · Users | `app/views/admin_users.py` | `/admin/users` | Admins only: list, create, role, deactivate, reset password |

The view files are named `views/` rather than `pages/` on purpose: Streamlit lists a `pages/` folder
for everyone, including anonymous visitors. Every view also calls `auth.require_sign_in()` first.
The Admin page is only listed for admins, but the API enforces the role on every call.

## Code

- `app/components/` – `auth` (sign-in and password-change forms), `account` (sidebar block), `models` (model picker), `chat` (hero and usage line), `styles`.
- `app/state/auth.py` – tokens and role in `st.session_state`; refreshes an expired access token once, otherwise signs out. `app/state/chat.py` – the open conversation.
- `app/clients/api_client.py` – every HTTP call: auth, models, `/ask`, `/chat` (plain and streaming), conversations and admin users.
- `demo_page.py` – standalone demo UI for `/ask`, kept exactly as imported. It sends no token, so the API now rejects it with 401.

## Tests

`tests/unit` covers the API client and navigation rules. `tests/app` drives the real pages with
Streamlit's `AppTest` against a mocked API (`respx`): `helpers.py` builds the app or a single view,
with or without a signed-in session. Nothing reaches a real API or provider.
