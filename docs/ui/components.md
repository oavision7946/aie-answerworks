# UI components and modules

| Module | Role |
|---|---|
| `app/main.py` | Page config, sign-in gate, password-change gate, navigation |
| `app/navigation.py` | `PAGES` and `visible_pages(is_admin)`: the page list and who sees it |
| `app/views/` | One script per page: `chat`, `conversations`, `documents`, `ask`, `admin_users`, `admin_corpora` |
| `app/components/auth.py` | Sign-in form and forced password-change form |
| `app/components/account.py` | Sidebar brand, signed-in email, sign out, API address |
| `app/components/models.py` | Model picker; prefers a given (provider, model), else the API's default |
| `app/components/rag.py` | Embedding/splitting pickers, index summary rows, the Sources section and the Chat sidebar's document controls |
| `app/components/chat.py` | Welcome banner and the model/tokens/cost line under answers |
| `app/state/auth.py` | Session tokens and role; `call_authenticated` refreshes once or signs out |
| `app/state/chat.py` | The open conversation: id, title and displayed messages |
| `app/clients/api_client.py` | All HTTP calls and the response models |

## Calling the API from a page

Pages never call `api_client` functions directly with a token. They go through `auth.call_authenticated(fn, *args)`, which adds the token, retries once after a refresh, and signs out if the session cannot be renewed:

```python
conversations = auth.call_authenticated(api_client.list_conversations)
```

API failures arrive as `RuntimeError` with the API's own message (for example "You cannot deactivate or demote your own account."), which pages show with `st.error`.

## Adding a page

1. Create `app/views/<name>.py`. Start it with `auth.require_sign_in()`.
2. Add a `PageSpec` to `PAGES` in `app/navigation.py` (set `admin_only=True` for admin pages).
3. Add the API calls to `api_client.py` and a test in `tests/app/` using `new_app(view=...)` or the full app with `switch_page`.

## Testing

`tests/app/helpers.py` provides `new_app(auth=..., view=...)`: the whole app by default, or a single view script. Pass `auth=None` for an anonymous session. API calls are mocked with `respx`.
