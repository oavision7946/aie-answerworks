# Authentication

The API uses bearer tokens (JWT, HS256). Accounts are created by an administrator; there is no self-registration endpoint (`/auth/register` returns 404).

## Configuration

| Setting | Where | Notes |
|---|---|---|
| `JWT_SECRET` | `.env` | Required, at least 16 characters. Without it, authenticated routes return 503. |
| `auth.access_token_ttl_minutes` | `config/app.yaml` | Default 15 |
| `auth.refresh_token_ttl_days` | `config/app.yaml` | Default 7 |

Passwords are hashed with Argon2. Login takes the same time whether or not the email exists.

## Endpoints

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/auth/login` | none | Exchange email and password for tokens |
| POST | `/auth/refresh` | refresh token in body | Issue a new token pair |
| GET | `/auth/me` | access token | Return the current user |
| POST | `/auth/change-password` | access token | Change own password (204) |

### Login

```bash
curl -s -X POST http://localhost:8000/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email": "ana@example.com", "password": "..."}'
```

Response:

```json
{"access_token": "...", "refresh_token": "...", "token_type": "bearer"}
```

Send the access token on every request:

```bash
curl -s http://localhost:8000/models -H "Authorization: Bearer $ACCESS_TOKEN"
```

### Refresh

```bash
curl -s -X POST http://localhost:8000/auth/refresh \
  -H 'Content-Type: application/json' \
  -d '{"refresh_token": "..."}'
```

Access and refresh tokens are not interchangeable: presenting one where the other is expected returns 401.

### Change password

The body holds `current_password` and `new_password` (12 to 128 characters). The new password must differ from the current one. Success clears the `must_change_password` flag.

## Status codes

| Code | Meaning |
|---|---|
| 400 | Wrong current password, or new password equal to the current one |
| 401 | Missing, invalid, expired or wrong-type token; bad credentials |
| 403 | Account deactivated, or password change required |
| 503 | `JWT_SECRET` is not configured |

## Account state

The user record is read on every request, so deactivating an account takes effect immediately, including for access tokens that have not expired. A user flagged `must_change_password` (new accounts and admin password resets) can only call `/auth/me` and `/auth/change-password` until the password is changed.
