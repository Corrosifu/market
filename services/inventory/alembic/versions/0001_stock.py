"""Stock, réservations et mouvements, identifiants compatibles avec le paquet v3."""

import sqlalchemy as sa
from alembic import op

revision = "0001_stock"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "stock",
        sa.Column("sku", sa.Text(), primary_key=True),
        sa.Column("available", sa.Integer(), nullable=False),
        sa.Column("reserved", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Text()),
        sa.Column("seller_id", sa.Text()),
        sa.Column("hub_id", sa.Text()),
        sa.Column("on_hand", sa.Integer()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("provenance_kind", sa.Text()),
        sa.CheckConstraint("available >= 0", name="stock_available_nonnegative"),
        sa.CheckConstraint("reserved >= 0", name="stock_reserved_nonnegative"),
        schema="inventory",
    )
    op.create_table(
        "stock_reservations",
        sa.Column("reservation_id", sa.Text(), primary_key=True),
        sa.Column("order_id", sa.Text(), nullable=True),
        sa.Column("sku", sa.Text(), sa.ForeignKey("inventory.stock.sku"), nullable=False),
        sa.Column("product_id", sa.Text()),
        sa.Column("seller_id", sa.Text()),
        sa.Column("hub_id", sa.Text()),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("provenance_kind", sa.Text()),
        sa.CheckConstraint("quantity > 0", name="reservation_quantity_positive"),
        sa.CheckConstraint("status IN ('RESERVED', 'CONFIRMED', 'RELEASED')", name="reservation_status"),
        schema="inventory",
    )
    op.create_index(
        "reservation_order_sku",
        "stock_reservations",
        ["order_id", "sku"],
        unique=True,
        postgresql_where=sa.text("order_id IS NOT NULL"),
        schema="inventory",
    )
    op.create_table(
        "inventory_movements",
        sa.Column("movement_id", sa.Text(), primary_key=True),
        sa.Column("sku", sa.Text(), sa.ForeignKey("inventory.stock.sku"), nullable=False),
        sa.Column("product_id", sa.Text()),
        sa.Column("seller_id", sa.Text()),
        sa.Column("hub_id", sa.Text()),
        sa.Column("order_item_id", sa.Text()),
        sa.Column("movement_type", sa.Text(), nullable=False),
        sa.Column("quantity_delta", sa.Integer(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provenance_kind", sa.Text()),
        schema="inventory",
    )


def downgrade() -> None:
    op.drop_table("inventory_movements", schema="inventory")
    op.drop_table("stock_reservations", schema="inventory")
    op.drop_table("stock", schema="inventory")
