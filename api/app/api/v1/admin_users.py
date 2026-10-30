import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.permissions import admin_user
from app.db.models import User
from app.db.repositories import user_repo
from app.db.session import get_session
from app.schemas.user import PasswordReset, UserCreate, UserOut, UserUpdate
from app.services import user_admin_service
from app.services.auth_service import AuthError

router = APIRouter(prefix="/admin/users", tags=["admin"])
Db = Annotated[Session, Depends(get_session)]
Admin = Annotated[User, Depends(admin_user)]


@router.post("", response_model=UserOut, status_code=201)
def create_user(body: UserCreate, db: Db, admin: Admin) -> User:
    """Create an account with a temporary password; the user must change it at first login."""
    try:
        return user_admin_service.create_user(db, body)
    except AuthError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc


@router.get("", response_model=list[UserOut])
def list_users(db: Db, admin: Admin) -> list[User]:
    return user_repo.list_users(db)


@router.patch("/{user_id}", response_model=UserOut)
def update_user(user_id: uuid.UUID, body: UserUpdate, db: Db, admin: Admin) -> User:
    """Set the role or activate/deactivate an account. You cannot lock yourself out."""
    try:
        return user_admin_service.update_user(db, admin, user_id, body)
    except AuthError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc


@router.post("/{user_id}/reset-password", response_model=UserOut)
def reset_password(user_id: uuid.UUID, body: PasswordReset, db: Db, admin: Admin) -> User:
    """Set a new temporary password; the user must change it at next login."""
    try:
        return user_admin_service.reset_password(db, user_id, body)
    except AuthError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc
