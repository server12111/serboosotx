"""add referrer_id to users

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-23

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("referrer_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=True))
    op.create_index("ix_users_referrer_id", "users", ["referrer_id"])


def downgrade() -> None:
    op.drop_index("ix_users_referrer_id", table_name="users")
    op.drop_column("users", "referrer_id")
