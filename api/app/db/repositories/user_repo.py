import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Role, User


def normalize_email(email: str) -> str:
    return email.strip().lower()


def get_by_id(db: Session, user_id: uuid.UUID) -> User | None:
    return db.get(User, user_id)


def get_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == normalize_email(email)))


def list_users(db: Session) -> list[User]:
    return list(db.scalars(select(User).order_by(User.created_at, User.email)))


def create(
    db: Session,
    email: str,
    password_hash: str,
    role: Role = Role.USER,
    must_change_password: bool = True,
) -> User:
    user = User(
        email=normalize_email(email),
        password_hash=password_hash,
        role=role,
        must_change_password=must_change_password,
    )
    db.add(user)
    db.commit()
    return user


def save(db: Session, user: User) -> User:
    db.add(user)
    db.commit()
    return user


def count_active_admins(db: Session) -> int:
    query = select(func.count()).select_from(User)
    query = query.where(User.role == Role.ADMIN, User.is_active.is_(True))
    return db.scalar(query) or 0
