"""add module_type and config to bot_instances

Revision ID: 6701424cfae4
Revises: e8c6f29cf841
Create Date: 2026-04-11 18:06:30.911005

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "6701424cfae4"
down_revision: Union[str, Sequence[str], None] = "e8c6f29cf841"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add module_type with server_default for existing rows
    op.add_column(
        "bot_instances",
        sa.Column(
            "module_type",
            sa.String(length=50),
            nullable=False,
            server_default="finance",
        ),
    )

    # Add config column (nullable, JSON type)
    op.add_column(
        "bot_instances",
        sa.Column("config", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("bot_instances", "config")
    op.drop_column("bot_instances", "module_type")
