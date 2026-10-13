"""model registry: config & catatan model

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-13 14:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("models", schema=None) as batch_op:
        batch_op.add_column(sa.Column("config", sa.JSON(), server_default="{}", nullable=False))
        batch_op.add_column(sa.Column("notes", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("models", schema=None) as batch_op:
        batch_op.drop_column("notes")
        batch_op.drop_column("config")
