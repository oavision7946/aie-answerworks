"""Admin-side user management. Raises AuthError for rule violations."""

import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.db.models import Role, User
from app.db.repositories import user_repo
from app.schemas.user import PasswordReset, UserCreate, UserUpdate
from app.services.auth_service import AuthError


def create_user(db: Session, data: UserCreate) -> User:
    if user_repo.get_by_email(db, data.email):
        raise AuthError(409, "A user with this email already exists.")
    try:
        return user_repo.create(
            db, data.email, hash_password(data.temporary_password), data.role, True
        )
    except IntegrityError as exc:  # lost a race with a concurrent create
        db.rollback()
        raise AuthError(409, "A user with this email already exists.") from exc


def _get(db: Session, user_id: uuid.UUID) -> User:
    user = user_repo.get_by_id(db, user_id)
    if user is None:
        raise AuthError(404, "User not found.")
    return user


def update_user(db: Session, acting: User, user_id: uuid.UUID, data: UserUpdate) -> User:
    user = _get(db, user_id)
    if user.id == acting.id and (data.is_active is False or data.role not in (None, Role.ADMIN)):
        raise AuthError(400, "You cannot deactivate or demote your own account.")
    if data.role is not None:
        user.role = data.role
    if data.is_active is not None:
        user.is_active = data.is_active
    return user_repo.save(db, user)


def reset_password(db: Session, user_id: uuid.UUID, data: PasswordReset) -> User:
    user = _get(db, user_id)
    user.password_hash = hash_password(data.temporary_password)
    user.must_change_password = True
    return user_repo.save(db, user)
