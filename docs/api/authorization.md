# Authorization

Every account has one role, `admin`, `monitor` or `user`, and an `is_active` flag. Roles stack: `monitor` can do everything a `user` can and also read the monitoring views, and `admin` can do everything a `monitor` can and also manage users and corpora. An account holds one role, so changing a user to `monitor` keeps all their regular abilities.

## Dependencies

Routes declare what they need with FastAPI dependencies from `app/core/permissions.py`:

| Dependency | Requires | Failure |
|---|---|---|
| `current_user` | valid access token for an existing, active user | 401 / 403 |
| `active_user` | `current_user` and no pending password change | 403 |
| `admin_user` | `active_user` with role `admin` | 403 |
| `monitoring_user` | `active_user` with role `admin` or `monitor` | 403 |

## Route matrix

| Route | Anonymous | User | Monitor | Admin |
|---|---|---|---|---|
| `GET /health`, `GET /health/ready` | allowed | allowed | allowed | allowed |
| `GET /ask` | allowed | allowed | allowed | allowed |
| `POST /ask`, `GET /models` | 401 | allowed | allowed | allowed |
| `/auth/login`, `/auth/refresh` | allowed | allowed | allowed | allowed |
| `/auth/me`, `/auth/change-password` | 401 | allowed (even with a pending password change) | allowed (even with a pending password change) | allowed |
| `/admin/users/*`, `GET /admin/status` | 401 | 403 | 403 | allowed |
| `GET /monitoring/status` | 401 | 403 | allowed | allowed |
| `GET /metrics` | 404 without `METRICS_TOKEN`; 401 without it as a bearer token | same | same | same |

## Lockout guard

An admin cannot deactivate or demote their own account (400). This keeps at least one working administrator.
