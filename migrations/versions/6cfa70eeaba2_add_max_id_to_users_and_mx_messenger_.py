"""add_max_id_to_users_and_mx_messenger_type

Revision ID: 6cfa70eeaba2
Revises: bbcf13923d1a
Create Date: 2026-04-25 11:53:00.001351

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "6cfa70eeaba2"
down_revision: Union[str, Sequence[str], None] = "bbcf13923d1a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add max_id column to users and update CheckConstraint on bot_instances."""
    # Add max_id column to users table
    op.add_column("users", sa.Column("max_id", sa.String(length=100), nullable=True))
    op.create_index(op.f("ix_users_max_id"), "users", ["max_id"], unique=True)

    # Update CheckConstraint on bot_instances to include 'MX'
    op.drop_constraint(
        "ck_bot_instances_messenger_type", "bot_instances", type_="check"
    )
    op.create_check_constraint(
        "ck_bot_instances_messenger_type",
        "bot_instances",
        "messenger_type IN ('TG', 'YM', 'MX')",
    )


def downgrade() -> None:
    """Remove max_id column and revert CheckConstraint."""
    # Revert CheckConstraint
    op.drop_constraint(
        "ck_bot_instances_messenger_type", "bot_instances", type_="check"
    )
    op.create_check_constraint(
        "ck_bot_instances_messenger_type",
        "bot_instances",
        "messenger_type IN ('TG', 'YM')",
    )

    # Drop max_id column
    op.drop_index(op.f("ix_users_max_id"), table_name="users")
    op.drop_column("users", "max_id")
