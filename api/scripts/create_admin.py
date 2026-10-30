"""Create the first administrator.

    cd api && uv run python -m scripts.create_admin

Reads BOOTSTRAP_ADMIN_EMAIL and BOOTSTRAP_ADMIN_PASSWORD from the environment/.env, or prompts
for whatever is missing. There is no default password. Refuses to run when an admin already
exists; further accounts are created through the admin API.
"""

import os
import re
import sys
from getpass import getpass

from sqlalchemy.orm import Session

from app.core.config import load_env
from app.core.security import hash_password
from app.db.models import Role
from app.db.repositories import user_repo
from app.db.session import get_engine
from app.schemas.auth import EMAIL_PATTERN, MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH


class BootstrapError(Exception):
    pass


def create_admin(db: Session, email: str, password: str) -> str:
    """Create the admin and return its normalized email."""
    email = user_repo.normalize_email(email)
    if not re.fullmatch(EMAIL_PATTERN, email):
        raise BootstrapError("The email address is not valid.")
    if not MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH:
        raise BootstrapError(
            f"The password must be {MIN_PASSWORD_LENGTH}-{MAX_PASSWORD_LENGTH} characters long."
        )
    if user_repo.count_active_admins(db) or user_repo.get_by_email(db, email):
        raise BootstrapError(
            "An admin or a user with this email already exists; nothing was changed."
        )
    user_repo.create(db, email, hash_password(password), Role.ADMIN, must_change_password=False)
    return email


def main() -> int:
    load_env()
    email = os.environ.get("BOOTSTRAP_ADMIN_EMAIL") or input("Admin email: ")
    password = os.environ.get("BOOTSTRAP_ADMIN_PASSWORD") or getpass("Admin password: ")
    try:
        with Session(get_engine()) as db:
            created = create_admin(db, email, password)
    except BootstrapError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Created admin {created}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
