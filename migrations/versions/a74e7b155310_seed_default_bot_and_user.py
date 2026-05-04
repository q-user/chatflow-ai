"""seed_default_bot_and_user

Revision ID: a74e7b155310
Revises: a0a47d65779a
Create Date: 2026-05-03 23:12:20.233400

Idempotent data migration:
- Creates a default user in the Default Company (if not exists)
- Creates a default MX bot instance (if not exists)

All UUIDs are deterministic so re-running is safe.
Bot token and secret are read from env vars (MX_BOT_TOKEN, MX_BOT_SECRET)
with fallbacks suitable for development.

"""

from typing import Sequence, Union
import os

from alembic import op
import sqlalchemy as sa


revision: str = "a74e7b155310"
down_revision: Union[str, Sequence[str], None] = "a0a47d65779a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DEFAULT_COMPANY_ID = "00000000-0000-0000-0000-000000000001"
DEFAULT_USER_ID = "00000000-0000-0000-0000-000000000002"
DEFAULT_BOT_ID = "00000000-0000-0000-0000-000000000010"


def _get_mx_credentials() -> tuple[str, str]:
    try:
        from infrastructure.config import settings

        return settings.mx_bot_token, settings.mx_bot_secret
    except Exception:
        return (
            os.environ.get("MX_BOT_TOKEN", "dev-mx-bot-token-placeholder"),
            os.environ.get("MX_BOT_SECRET", "dev-mx-bot-secret-placeholder"),
        )


def upgrade() -> None:
    conn = op.get_bind()

    existing_user = conn.execute(
        sa.text("SELECT id FROM users WHERE id = :uid"),
        {"uid": DEFAULT_USER_ID},
    ).fetchone()

    if existing_user is None:
        conn.execute(
            sa.text(
                "INSERT INTO users (id, email, hashed_password, is_active, "
                "company_id, is_superuser, is_verified, max_id) "
                "VALUES (:id, :email, :hash, true, :cid, false, false, :max_id)"
            ),
            {
                "id": DEFAULT_USER_ID,
                "email": "default@chatflow.ai",
                "hash": "$2b$12$NOTAREALHASHXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX",
                "cid": DEFAULT_COMPANY_ID,
                "max_id": "default_max_user",
            },
        )

    existing_bot = conn.execute(
        sa.text("SELECT id FROM bot_instances WHERE id = :bid"),
        {"bid": DEFAULT_BOT_ID},
    ).fetchone()

    if existing_bot is None:
        bot_token, bot_secret = _get_mx_credentials()

        conn.execute(
            sa.text(
                "INSERT INTO bot_instances "
                "(id, company_id, messenger_type, token, secret, status, module_type, config) "
                "VALUES (:id, :cid, 'MX', :token, :secret, 'active', 'finance', :config)"
            ),
            {
                "id": DEFAULT_BOT_ID,
                "cid": DEFAULT_COMPANY_ID,
                "token": bot_token,
                "secret": bot_secret,
                "config": '{"system_prompt": null}',
            },
        )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text("DELETE FROM bot_instances WHERE id = :bid"),
        {"bid": DEFAULT_BOT_ID},
    )
    conn.execute(
        sa.text("DELETE FROM users WHERE id = :uid"),
        {"uid": DEFAULT_USER_ID},
    )
