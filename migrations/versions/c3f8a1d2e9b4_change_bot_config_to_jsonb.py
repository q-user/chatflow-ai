"""change bot_instances.config from JSON to JSONB

Revision ID: c3f8a1d2e9b4
Revises: a74e7b155310
Create Date: 2026-05-04 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "c3f8a1d2e9b4"
down_revision: Union[str, Sequence[str], None] = "a74e7b155310"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "bot_instances",
        "config",
        type_=JSONB,
        postgresql_using="config::jsonb",
    )


def downgrade() -> None:
    op.alter_column(
        "bot_instances",
        "config",
        type_=sa.JSON(),
        postgresql_using="config::json",
    )
