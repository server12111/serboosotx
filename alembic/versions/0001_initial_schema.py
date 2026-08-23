"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-08-23

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tg_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(64), nullable=True),
        sa.Column("full_name", sa.String(255), nullable=True),
        sa.Column("balance", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("is_banned", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("balance >= 0", name="ck_users_balance_nonnegative"),
    )
    op.create_index("ix_users_tg_id", "users", ["tg_id"], unique=True)

    op.create_table(
        "services",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("external_service_id", sa.String(64), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("category_raw", sa.Text(), nullable=True),
        sa.Column("type_raw", sa.Text(), nullable=True),
        sa.Column("platform", sa.String(32), nullable=False),
        sa.Column("rate_rub", sa.Numeric(14, 4), nullable=False),
        sa.Column("min_quantity", sa.Integer(), nullable=False),
        sa.Column("max_quantity", sa.Integer(), nullable=False),
        sa.Column("refill", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("cancel", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("dripfeed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_services_external_service_id", "services", ["external_service_id"], unique=True)
    op.create_index("ix_services_platform_active", "services", ["platform", "is_active"])

    op.create_table(
        "orders",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("service_id", sa.BigInteger(), sa.ForeignKey("services.id"), nullable=False),
        sa.Column("external_order_id", sa.String(64), nullable=True),
        sa.Column("link", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("runs", sa.Integer(), nullable=True),
        sa.Column("interval_minutes", sa.Integer(), nullable=True),
        sa.Column("charge_rub", sa.Numeric(14, 2), nullable=False),
        sa.Column("upstream_cost_rub", sa.Numeric(14, 4), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("start_count", sa.Integer(), nullable=True),
        sa.Column("remains", sa.Integer(), nullable=True),
        sa.Column("upstream_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_orders_user_created", "orders", ["user_id", "created_at"])
    op.create_index(
        "ix_orders_open",
        "orders",
        ["last_checked_at"],
        postgresql_where=sa.text("status NOT IN ('completed','canceled','failed','refunded')"),
    )

    op.create_table(
        "cryptobot_invoices",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("cryptobot_invoice_id", sa.BigInteger(), nullable=False),
        sa.Column("asset", sa.String(16), nullable=False),
        sa.Column("amount_crypto", sa.Numeric(20, 8), nullable=False),
        sa.Column("amount_rub_locked", sa.Numeric(14, 2), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("pay_url", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_cryptobot_invoices_cryptobot_invoice_id",
        "cryptobot_invoices",
        ["cryptobot_invoice_id"],
        unique=True,
    )
    op.create_index("ix_cryptobot_invoices_status", "cryptobot_invoices", ["status"])

    op.create_table(
        "balance_transactions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("type", sa.String(24), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("balance_after", sa.Numeric(14, 2), nullable=False),
        sa.Column("related_order_id", sa.BigInteger(), sa.ForeignKey("orders.id"), nullable=True),
        sa.Column(
            "related_invoice_id", sa.BigInteger(), sa.ForeignKey("cryptobot_invoices.id"), nullable=True
        ),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_balance_tx_user_created", "balance_transactions", ["user_id", "created_at"])

    op.create_table(
        "settings",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
    )

    op.create_table(
        "admin_actions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("admin_tg_id", sa.BigInteger(), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("target_user_id", sa.BigInteger(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("admin_actions")
    op.drop_table("settings")
    op.drop_index("ix_balance_tx_user_created", table_name="balance_transactions")
    op.drop_table("balance_transactions")
    op.drop_index("ix_cryptobot_invoices_status", table_name="cryptobot_invoices")
    op.drop_index("ix_cryptobot_invoices_cryptobot_invoice_id", table_name="cryptobot_invoices")
    op.drop_table("cryptobot_invoices")
    op.drop_index("ix_orders_open", table_name="orders")
    op.drop_index("ix_orders_user_created", table_name="orders")
    op.drop_table("orders")
    op.drop_index("ix_services_platform_active", table_name="services")
    op.drop_index("ix_services_external_service_id", table_name="services")
    op.drop_table("services")
    op.drop_index("ix_users_tg_id", table_name="users")
    op.drop_table("users")
