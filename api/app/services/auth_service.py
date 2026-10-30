"""Login, token refresh and password changes. Raises AuthError; routes map it to HTTP."""

import logging
from datetime import timedelta

from sqlalchemy.orm import Session

from app.core.security import (
    SecretNotConfiguredError,
    TokenError,
    TokenType,
    create_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.core.settings import Settings
from app.db.models import User
from app.db.repositories import user_repo
from app.schemas.auth import TokenResponse

logger = logging.getLogger(__name__)


class AuthError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


BAD_CREDENTIALS = AuthError(401, "Incorrect email or password.")
DEACTIVATED = AuthError(403, "This account is deactivated. Contact an administrator.")
INVALID_REFRESH = AuthError(401, "The refresh token is invalid or expired. Please sign in again.")


def issue_tokens(user: User, settings: Settings) -> TokenResponse:
    access_ttl = timedelta(minutes=settings.app.auth.access_token_ttl_minutes)
    refresh_ttl = timedelta(days=settings.app.auth.refresh_token_ttl_days)
    secret = settings.env.jwt_secret
    try:
        return TokenResponse(
            access_token=create_token(user.id, TokenType.ACCESS, access_ttl, secret),
            refresh_token=create_token(user.id, TokenType.REFRESH, refresh_ttl, secret),
            expires_in=int(access_ttl.total_seconds()),
            must_change_password=user.must_change_password,
        )
    except SecretNotConfiguredError as exc:
        logger.error("Authentication is not configured: %s", exc)
        raise AuthError(503, "Authentication is not configured on this server.") from exc


def login(db: Session, settings: Settings, email: str, password: str) -> TokenResponse:
    user = user_repo.get_by_email(db, email)
    # Always runs one Argon2 verification, even for unknown emails.
    if not verify_password(password, user.password_hash if user else None) or user is None:
        raise BAD_CREDENTIALS
    if not user.is_active:
        raise DEACTIVATED
    return issue_tokens(user, settings)


def refresh(db: Session, settings: Settings, refresh_token: str) -> TokenResponse:
    try:
        user_id = decode_token(refresh_token, TokenType.REFRESH, settings.env.jwt_secret)
    except TokenError as exc:
        raise INVALID_REFRESH from exc
    except SecretNotConfiguredError as exc:
        logger.error("Authentication is not configured: %s", exc)
        raise AuthError(503, "Authentication is not configured on this server.") from exc
    user = user_repo.get_by_id(db, user_id)
    if user is None:
        raise INVALID_REFRESH
    if not user.is_active:
        raise DEACTIVATED
    return issue_tokens(user, settings)


def change_password(db: Session, user: User, current_password: str, new_password: str) -> None:
    if not verify_password(current_password, user.password_hash):
        raise AuthError(400, "The current password is incorrect.")
    if new_password == current_password:
        raise AuthError(400, "The new password must differ from the current one.")
    user.password_hash = hash_password(new_password)
    user.must_change_password = False
    user_repo.save(db, user)
