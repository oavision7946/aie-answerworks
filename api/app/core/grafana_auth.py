"""Tokens that let a signed-in monitor or administrator into the Grafana dashboards.

Grafana sits behind the API (`/monitoring/grafana/...`) and trusts only a signed assertion that
the API adds to each request. Three short tokens are involved, all signed with
MONITORING_JWT_SECRET, which is not the secret that signs access tokens:

- launch token: carried once in the dashboard link, valid for minutes, good for a single use
- session token: kept in an HttpOnly cookie after the link is used
- assertion: sent to Grafana with every proxied request, valid for a minute
"""

import threading
import time
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from enum import StrEnum

import jwt

from app.core.security import JWT_ALGORITHM, MIN_SECRET_LENGTH, SecretNotConfiguredError, TokenError

LAUNCH_TTL = timedelta(minutes=5)
SESSION_TTL = timedelta(hours=1)
ASSERTION_TTL = timedelta(minutes=1)
ASSERTION_ISSUER = "answerworks"
GRAFANA_ROLE = "Viewer"


class GrafanaTokenType(StrEnum):
    LAUNCH = "monitoring_launch"
    SESSION = "monitoring_session"


_used: dict[str, float] = {}  # launch token id -> expiry; per process, like the other telemetry
_used_lock = threading.Lock()


def _check_secret(secret: str) -> None:
    if len(secret) < MIN_SECRET_LENGTH:
        raise SecretNotConfiguredError(
            f"MONITORING_JWT_SECRET must be at least {MIN_SECRET_LENGTH} characters long"
        )


def _encode(claims: Mapping[str, object], ttl: timedelta, secret: str) -> str:
    _check_secret(secret)
    now = datetime.now(UTC)
    return jwt.encode({**claims, "iat": now, "exp": now + ttl}, secret, algorithm=JWT_ALGORITHM)


def _decode(token: str, kind: GrafanaTokenType, secret: str) -> dict[str, object]:
    _check_secret(secret)
    try:
        claims: dict[str, object] = jwt.decode(
            token, secret, algorithms=[JWT_ALGORITHM], options={"require": ["exp", "sub", "type"]}
        )
    except jwt.PyJWTError as exc:
        raise TokenError(str(exc)) from exc
    if claims["type"] != kind.value:
        raise TokenError("wrong token type")
    return claims


def _user_id(claims: dict[str, object]) -> uuid.UUID:
    try:
        return uuid.UUID(str(claims["sub"]))
    except ValueError as exc:
        raise TokenError(str(exc)) from exc


def launch_token(user_id: uuid.UUID, secret: str) -> str:
    claims = {"sub": str(user_id), "type": GrafanaTokenType.LAUNCH.value, "jti": uuid.uuid4().hex}
    return _encode(claims, LAUNCH_TTL, secret)


def redeem_launch_token(token: str, secret: str) -> uuid.UUID:
    """The user a launch token was issued to. A second use of the same token is refused."""
    claims = _decode(token, GrafanaTokenType.LAUNCH, secret)
    user_id = _user_id(claims)
    now = time.time()
    with _used_lock:
        for jti in [jti for jti, expires in _used.items() if expires < now]:
            del _used[jti]
        jti = str(claims.get("jti", ""))
        if not jti or jti in _used:
            raise TokenError("launch token already used")
        _used[jti] = float(str(claims["exp"]))
    return user_id


def session_token(user_id: uuid.UUID, secret: str) -> str:
    return _encode(
        {"sub": str(user_id), "type": GrafanaTokenType.SESSION.value}, SESSION_TTL, secret
    )


def session_user_id(token: str, secret: str) -> uuid.UUID:
    return _user_id(_decode(token, GrafanaTokenType.SESSION, secret))


def grafana_assertion(email: str, secret: str) -> str:
    """The signed identity Grafana reads from `X-JWT-Assertion`; everyone is a Viewer there."""
    claims = {"iss": ASSERTION_ISSUER, "sub": email, "role": GRAFANA_ROLE}
    return _encode(claims, ASSERTION_TTL, secret)


def reset() -> None:
    """Forget used launch tokens (tests)."""
    with _used_lock:
        _used.clear()
