"""add service_type to services

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-23

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # nullable=True initially since existing rows have no value yet; catalog_sync's
    # next run backfills every row (it re-upserts the whole catalog each cycle), then
    # the NOT NULL is enforced. A fresh install seeds it via the initial sync instead.
    op.add_column("services", sa.Column("service_type", sa.String(32), nullable=True))
    op.execute("UPDATE services SET service_type = 'other' WHERE service_type IS NULL")
    op.alter_column("services", "service_type", nullable=False)
    op.create_index(
        "ix_services_platform_type_active", "services", ["platform", "service_type", "is_active"]
    )


def downgrade() -> None:
    op.drop_index("ix_services_platform_type_active", table_name="services")
    op.drop_column("services", "service_type")
