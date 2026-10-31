# Admin guide

## Bootstrap the first admin

Accounts are created by admins, so the first one comes from a script. Set `DATABASE_URL` and `JWT_SECRET` in `.env`, run the migrations, then:

```bash
make migrate
make create-admin
```

The script prompts for an email and password. For non-interactive use, set `BOOTSTRAP_ADMIN_EMAIL` and `BOOTSTRAP_ADMIN_PASSWORD` in the environment. It refuses to run if an active admin already exists or the email is taken, and there is no default password. The admin it creates is not forced to change the password.

## Sign in as admin

```bash
curl -s -X POST http://localhost:8000/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email": "admin@example.com", "password": "..."}'
```

Use the returned `access_token` as a bearer token in the calls below, or use the interactive docs at `/docs`.

## Manage users

All routes need an admin access token.

| Action | Request |
|---|---|
| Create | `POST /admin/users` with `email` and `temporary_password` (optional `role`) |
| List | `GET /admin/users` |
| Change role or active flag | `PATCH /admin/users/{id}` with `role` and/or `is_active` |
| Reset password | `POST /admin/users/{id}/reset-password` with `temporary_password` |

```bash
curl -s -X POST http://localhost:8000/admin/users \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"email": "ana@example.com", "temporary_password": "a-long-temporary-pass"}'
```

Temporary passwords follow the same length rules as normal ones (12 to 128 characters). Share the temporary password with the user over a secure channel. On first sign-in they must set their own password before using the app.

Emails are stored lowercased. Creating a duplicate returns 409.

## Deactivate a user

```bash
curl -s -X PATCH http://localhost:8000/admin/users/$USER_ID \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"is_active": false}'
```

The user is locked out immediately, even with an unexpired token. You cannot deactivate or demote yourself.

## Known limits

Login attempts are not rate limited.
