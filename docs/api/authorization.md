# Authorization

Every account has one role, `admin` or `user`, and an `is_active` flag.

## Dependencies

Routes declare what they need with FastAPI dependencies from `app/core/permissions.py`:

| Dependency | Requires | Failure |
|---|---|---|
| `current_user` | valid access token for an existing, active user | 401 / 403 |
| `active_user` | `current_user` and no pending password change | 403 |
| `admin_user` | `active_user` with role `admin` | 403 |

## Route matrix

| Route | Anonymous | User | Admin |
|---|---|---|---|
| `GET /health` | allowed | allowed | allowed |
| `GET /ask` | allowed | allowed | allowed |
| `POST /ask`, `GET /models` | 401 | allowed | allowed |
| `/auth/login`, `/auth/refresh` | allowed | allowed | allowed |
| `/auth/me`, `/auth/change-password` | 401 | allowed (even with a pending password change) | allowed |
| `/admin/users/*` | 401 | 403 | allowed |

## Lockout guard

An admin cannot deactivate or demote their own account (400). This keeps at least one working administrator.
