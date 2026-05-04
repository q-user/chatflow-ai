"""add_secret_to_bot_instances

Revision ID: a0a47d65779a
Revises: 6cfa70eeaba2
Create Date: 2026-04-25 12:42:09.825009

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a0a47d65779a"
down_revision: Union[str, Sequence[str], None] = "6cfa70eeaba2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add secret column to bot_instances."""
    op.add_column(
        "bot_instances", sa.Column("secret", sa.String(length=512), nullable=True)
    )


def downgrade() -> None:
    """Remove secret column from bot_instances."""
    op.drop_column("bot_instances", "secret")
