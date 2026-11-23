"""Crée les paiements, compatibles avec les captures et remboursements du paquet."""

import sqlalchemy as sa
from alembic import op

revision = "payment_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "payments",
        sa.Column("payment_id", sa.Text(), primary_key=True),
        sa.Column("order_id", sa.Text(), nullable=False),
        sa.Column("shipment_id", sa.Text()),
        sa.Column("payment_type", sa.Text(), nullable=False),
        sa.Column("method", sa.Text()),
        sa.Column("amount_gbp", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.Text(), nullable=False, server_default="GBP"),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("provenance_kind", sa.Text()),
        sa.CheckConstraint("amount_gbp > 0", name="payment_amount_positive"),
        sa.CheckConstraint("payment_type IN ('CAPTURE', 'REFUND')", name="payment_type"),
        sa.CheckConstraint("status IN ('CAPTURED', 'DECLINED', 'SUCCEEDED')", name="payment_status"),
        schema="payment",
    )
    op.create_index(
        "api_capture_order",
        "payments",
        ["order_id"],
        unique=True,
        postgresql_where=sa.text("payment_type = 'CAPTURE' AND provenance_kind IS NULL"),
        schema="payment",
    )


def downgrade() -> None:
    op.drop_table("payments", schema="payment")
