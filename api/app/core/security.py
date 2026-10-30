"""Password hashing (Argon2) and signed JWT access/refresh tokens."""

import uuid
from datetime import UTC, datetime, timedelta
from enum import StrEnum

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

JWT_ALGORITHM = "HS256"
MIN_SECRET_LENGTH = 16

_hasher = PasswordHasher()
# Verified against when an email is unknown, so login timing doesn't reveal which emails exist.
_DUMMY_HASH = _hasher.hash("not-a-real-password")


class TokenType(StrEnum):
    ACCESS = "access"
    REFRESH = "refresh"


class TokenError(Exception):
    """The token is missing, malformed, expired, tampered with, or of the wrong type."""


class SecretNotConfiguredError(Exception):
    """JWT_SECRET is empty or too short to sign tokens safely."""


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    """True when the password matches. A None hash (unknown user) burns equal time and fails."""
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerificationError, InvalidHashError):
        return False


def _check_secret(secret: str) -> None:
    if len(secret) < MIN_SECRET_LENGTH:
        raise SecretNotConfiguredError(
            f"JWT_SECRET must be at least {MIN_SECRET_LENGTH} characters long"
        )


def create_token(subject: uuid.UUID, token_type: TokenType, ttl: timedelta, secret: str) -> str:
    _check_secret(secret)
    now = datetime.now(UTC)
    claims = {"sub": str(subject), "type": token_type.value, "iat": now, "exp": now + ttl}
    return jwt.encode(claims, secret, algorithm=JWT_ALGORITHM)


def decode_token(token: str, expected_type: TokenType, secret: str) -> uuid.UUID:
    """The user id carried by a valid token of the expected type; TokenError otherwise."""
    _check_secret(secret)
    try:
        claims = jwt.decode(
            token, secret, algorithms=[JWT_ALGORITHM], options={"require": ["exp", "sub", "type"]}
        )
        if claims["type"] != expected_type.value:
            raise TokenError("wrong token type")
        return uuid.UUID(claims["sub"])
    except (jwt.PyJWTError, ValueError) as exc:
        raise TokenError(str(exc)) from exc
