"""add multi-tenant schema with companies and bot instances

Revision ID: e8c6f29cf841
Revises: bf879aff99fb
Create Date: 2026-04-11 12:19:13.236223

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'e8c6f29cf841'
down_revision: Union[str, Sequence[str], None] = 'bf879aff99fb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.
    
    Order matters:
    1. CREATE companies (must exist before users.company_id FK)
    2. ALTER users: add columns (company_id nullable first, then data migration, then NOT NULL)
    3. CREATE bot_instances
    4. CREATE indexes
    """
    # ============================================================
    # 1. CREATE TABLE companies
    # ============================================================
    op.create_table(
        "companies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # ============================================================
    # 2. ALTER TABLE users: add new columns
    # ============================================================
    # Step 2a: Add company_id as nullable (for data migration)
    op.add_column(
        "users",
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=True),
    )

    # Step 2b: Add fastapi-users required columns
    op.add_column(
        "users",
        sa.Column(
            "is_superuser",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "is_verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    # Step 2c: Add messenger ID columns
    op.add_column(
        "users",
        sa.Column("telegram_id", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("yandex_id", sa.String(length=100), nullable=True),
    )

    # ============================================================
    # 3. DATA MIGRATION: create default company for existing users
    # ============================================================
    companies_table = sa.table(
        "companies",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("name", sa.String),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    users_table = sa.table(
        "users",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("company_id", postgresql.UUID(as_uuid=True)),
    )

    # Insert default company with a deterministic UUID
    default_company_id = "00000000-0000-0000-0000-000000000001"
    op.execute(
        companies_table.insert().values(
            id=default_company_id,
            name="Default Company",
            created_at=sa.func.now(),
        )
    )

    # Assign all existing users to the default company
    op.execute(
        users_table.update()
        .where(users_table.c.company_id == sa.null())
        .values(company_id=default_company_id)
    )

    # ============================================================
    # 4. Enforce NOT NULL on company_id + add FK
    # ============================================================
    op.alter_column("users", "company_id", nullable=False)
    op.create_foreign_key(
        "fk_users_company_id_companies",
        "users",
        "companies",
        ["company_id"],
        ["id"],
    )

    # ============================================================
    # 5. CREATE TABLE bot_instances
    # ============================================================
    op.create_table(
        "bot_instances",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "company_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("messenger_type", sa.String(length=10), nullable=False),
        sa.Column("token", sa.String(length=512), nullable=False),
        sa.Column("status", sa.String(length=20), server_default=sa.text("'active'")),
        sa.CheckConstraint(
            "messenger_type IN ('TG', 'YM')",
            name="ck_bot_instances_messenger_type",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name="fk_bot_instances_company_id_companies",
        ),
    )

    # ============================================================
    # 6. CREATE INDEXes
    # ============================================================
    # Users indexes
    op.create_index("ix_users_company_id", "users", ["company_id"], unique=False)
    op.create_index("ix_users_telegram_id", "users", ["telegram_id"], unique=False)
    op.create_index("ix_users_yandex_id", "users", ["yandex_id"], unique=False)
    op.create_unique_constraint("uq_users_telegram_id", "users", ["telegram_id"])
    op.create_unique_constraint("uq_users_yandex_id", "users", ["yandex_id"])

    # Bot instances indexes
    op.create_index(
        "ix_bot_instances_company_id", "bot_instances", ["company_id"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Drop indexes
    op.drop_index("ix_bot_instances_company_id", table_name="bot_instances")
    op.drop_index("ix_users_yandex_id", table_name="users")
    op.drop_index("ix_users_telegram_id", table_name="users")
    op.drop_index("ix_users_company_id", table_name="users")

    # Drop unique constraints
    op.drop_constraint("uq_users_yandex_id", "users", type_="unique")
    op.drop_constraint("uq_users_telegram_id", "users", type_="unique")

    # Drop tables
    op.drop_table("bot_instances")

    # Drop FK
    op.drop_constraint("fk_users_company_id_companies", "users", type_="foreignkey")

    # Drop columns from users
    op.drop_column("users", "yandex_id")
    op.drop_column("users", "telegram_id")
    op.drop_column("users", "is_verified")
    op.drop_column("users", "is_superuser")
    op.drop_column("users", "company_id")

    # Drop companies table
    op.drop_table("companies")
