"""add the monitor role

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-03
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def _sqlite_role(*values: str) -> None:
    # SQLite keeps the role as VARCHAR sized to the longest value; rebuild the column to match.
    with op.batch_alter_table("users") as batch:
        batch.alter_column(
            "role", type_=sa.Enum(*values, name="user_role"), existing_nullable=False
        )


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        # ADD VALUE cannot run inside a transaction block on older servers.
        with op.get_context().autocommit_block():
            op.execute("ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'monitor'")
    elif dialect == "sqlite":
        _sqlite_role("admin", "monitor", "user")


def downgrade() -> None:
    op.execute("UPDATE users SET role = 'user' WHERE role = 'monitor'")
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        _sqlite_role("admin", "user")
    elif dialect == "postgresql":
        op.execute("ALTER TYPE user_role RENAME TO user_role_old")
        op.execute("CREATE TYPE user_role AS ENUM ('admin', 'user')")
        op.execute("ALTER TABLE users ALTER COLUMN role TYPE user_role USING role::text::user_role")
        op.execute("DROP TYPE user_role_old")
