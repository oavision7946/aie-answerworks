"""scheduled refresh and last ingestion status for corpora

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-02
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("corpora", sa.Column("refresh_minutes", sa.Integer()))
    op.add_column("corpora", sa.Column("last_ingested_at", sa.DateTime(timezone=True)))
    op.add_column("corpora", sa.Column("last_ingest_error", sa.Text()))


def downgrade() -> None:
    op.drop_column("corpora", "last_ingest_error")
    op.drop_column("corpora", "last_ingested_at")
    op.drop_column("corpora", "refresh_minutes")
