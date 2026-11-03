"""Authentication and authorization dependencies for protected routes.

- current_user:  valid access token for an existing, active user (password change may be pending)
- active_user:   current_user whose password change is not pending (use on normal routes)
- admin_user:    active_user with the admin role
- monitoring_user: active_user with the admin or monitor role
"""

from typing import Annotated

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.security import SecretNotConfiguredError, TokenError, TokenType, decode_token
from app.core.settings import Settings, get_settings
from app.db.models import Role, User
from app.db.repositories import user_repo
from app.db.session import get_session

bearer_scheme = HTTPBearer(auto_error=False, description="Access token from POST /auth/login")
_BEARER = {"WWW-Authenticate": "Bearer"}


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(status_code=401, detail=detail, headers=_BEARER)


def current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> User:
    if credentials is None:
        raise _unauthorized("Not authenticated.")
    try:
        user_id = decode_token(credentials.credentials, TokenType.ACCESS, settings.env.jwt_secret)
    except TokenError as exc:
        raise _unauthorized("The access token is invalid or expired.") from exc
    except SecretNotConfiguredError as exc:
        raise HTTPException(503, "Authentication is not configured on this server.") from exc
    user = user_repo.get_by_id(db, user_id)
    if user is None:
        raise _unauthorized("The access token is invalid or expired.")
    if not user.is_active:
        raise HTTPException(403, "This account is deactivated. Contact an administrator.")
    return user


def active_user(user: Annotated[User, Depends(current_user)]) -> User:
    if user.must_change_password:
        raise HTTPException(403, "Password change required. Use POST /auth/change-password.")
    return user


def admin_user(user: Annotated[User, Depends(active_user)]) -> User:
    if user.role != Role.ADMIN:
        raise HTTPException(403, "Administrator access is required.")
    return user


def monitoring_user(user: Annotated[User, Depends(active_user)]) -> User:
    if user.role not in (Role.ADMIN, Role.MONITOR):
        raise HTTPException(403, "Monitoring access is required.")
    return user
