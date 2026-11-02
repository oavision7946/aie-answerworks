# UI overview

The UI is a Streamlit app that talks to the API over HTTP only. It never touches the database or a model provider directly. Set `API_BASE_URL` to point it at a different API (default `http://127.0.0.1:8000`).

## Flow

1. **Sign in.** Anonymous visitors see only the sign-in form. The app stores the access and refresh tokens in the session and reads the user's role from `GET /auth/me`.
2. **Password change.** An account with a pending change sees only the "choose a new password" form. Nothing else loads until it is done.
3. **Navigation.** The pages below are listed in the sidebar, with the user's email, **Sign out** and the API address under them.
4. **Expired tokens.** An access token that the API rejects is refreshed once, transparently. If that fails, the session ends with a notice and the sign-in form returns.

## Pages

| Page | Who | What it does |
|---|---|---|
| Chat | everyone | Sends messages to `POST /chat`. The conversation is stored and earlier messages are sent to the model. Model picker, streaming toggle, and model, tokens and cost under every answer. "New chat" starts over. |
| Conversations | everyone | Lists your conversations (model, last activity). **Open** resumes one in Chat with its full history; **Rename**; **Delete** after a confirmation. |
| Documents | everyone | **My uploads**: upload a file with a chosen embedding model and splitting strategy, see how each document was indexed, view its chunks, add another index, delete. **Shared corpora**: browse the corpora you can read (read-only). The two are separate sections. |
| Ask | everyone | Question-answer through `POST /ask`: one question, one answer, nothing stored. Useful for one-off questions and for comparing models. |
| Admin · Users | admins | Table of accounts; create a user with a temporary password; change role, deactivate or reactivate; reset a password. |
| Admin · Corpora | admins | Create corpora, set the public flag, grant and revoke users, upload documents or ingest the configured source now, see the source, refresh interval, last run and last problem, see each file's status and indexes, delete. |
| Admin · System | admins | Is everything working: database and schema, model providers and their call results, embedding models, corpora and their last ingestion, row counts and request totals. **Refresh** reloads it. |

## Chat with documents

The Chat sidebar has an **Answer from my documents** switch. When it is on, **Retrieval settings** let you pick the embedding model, the splitting strategy and which shared corpora to search. Answers then show a **Sources** section: each passage with its file, similarity and the index (embedding model and strategy) it came from. Sources are kept when you reopen the conversation, as long as you can still read those documents. See [RAG](../rag.md).

## Chat and Ask: why both

Chat remembers; Ask does not. They use the same providers, models, streaming and usage reporting, so you can start a conversation or just fire a question without leaving a trace.

When a chat message fails, the page says so and that the message was not saved: the API stores a message only after the model has answered, so sending it again is safe.

## Security notes

- The Admin page is only listed for admins, but this is a convenience. The API checks the role on every call, so a regular user's token gets 403 from the admin routes whatever the UI shows.
- Page files live in `app/views/` and call `auth.require_sign_in()` first, so no page renders for an anonymous session.
- Tokens live in the Streamlit session (server memory), not in the browser's storage.
