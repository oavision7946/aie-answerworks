from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.permissions import current_user
from app.core.settings import Settings, get_settings
from app.db.models import User
from app.db.session import get_session
from app.schemas.auth import ChangePasswordRequest, LoginRequest, RefreshRequest, TokenResponse
from app.schemas.user import UserOut
from app.services import auth_service
from app.services.auth_service import AuthError

router = APIRouter(prefix="/auth", tags=["auth"])
Db = Annotated[Session, Depends(get_session)]
Config = Annotated[Settings, Depends(get_settings)]


def _http(exc: AuthError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Db, settings: Config) -> TokenResponse:
    """Exchange an email and password for an access and a refresh token."""
    try:
        return auth_service.login(db, settings, body.email, body.password)
    except AuthError as exc:
        raise _http(exc) from exc


@router.post("/refresh", response_model=TokenResponse)
def refresh(body: RefreshRequest, db: Db, settings: Config) -> TokenResponse:
    """Exchange a refresh token for a new token pair. Fails for deactivated users."""
    try:
        return auth_service.refresh(db, settings, body.refresh_token)
    except AuthError as exc:
        raise _http(exc) from exc


@router.get("/me", response_model=UserOut)
def me(user: Annotated[User, Depends(current_user)]) -> User:
    """The signed-in user. Also works while a password change is pending."""
    return user


@router.post("/change-password", status_code=204)
def change_password(
    body: ChangePasswordRequest, user: Annotated[User, Depends(current_user)], db: Db
) -> None:
    """Change your own password; clears the forced-change flag."""
    try:
        auth_service.change_password(db, user, body.current_password, body.new_password)
    except AuthError as exc:
        raise _http(exc) from exc
