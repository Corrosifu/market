"""Commandes partitionnées, étapes de saga, idempotence et outbox."""

from alembic import op

revision = "order_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""CREATE TABLE orders.orders (
        id TEXT NOT NULL, ordered_at TIMESTAMPTZ NOT NULL DEFAULT now(), customer_id TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('PENDING', 'CONFIRMED', 'CANCELLED')),
        historical_status TEXT NULL, currency TEXT NOT NULL DEFAULT 'GBP', total_gbp NUMERIC(12,2) NULL,
        provenance_kind TEXT NULL, PRIMARY KEY (id, ordered_at)
    ) PARTITION BY RANGE (ordered_at)""")
    for year in (2026, 2027):
        for month in range(1, 13):
            next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)
            op.execute(f"""CREATE TABLE orders.orders_{year}_{month:02d} PARTITION OF orders.orders
                FOR VALUES FROM ('{year}-{month:02d}-01') TO ('{next_year}-{next_month:02d}-01')""")
    op.execute("CREATE TABLE orders.orders_default PARTITION OF orders.orders DEFAULT")
    op.execute("""CREATE TABLE orders.order_lines (
        id TEXT PRIMARY KEY, order_id TEXT NOT NULL, sku TEXT NOT NULL,
        quantity INTEGER NOT NULL CHECK (quantity > 0), unit_price_gbp NUMERIC(12,2) NULL,
        product_id TEXT NULL, seller_id TEXT NULL, provenance_kind TEXT NULL
    )""")
    op.execute("CREATE INDEX order_lines_order ON orders.order_lines (order_id)")
    op.execute("""CREATE TABLE orders.saga_instances (
        order_id TEXT PRIMARY KEY, ordered_at TIMESTAMPTZ NOT NULL,
        step TEXT NOT NULL, owner TEXT NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        simulate_failure BOOLEAN NOT NULL DEFAULT false,
        reason TEXT NULL, response_code INTEGER NULL,
        FOREIGN KEY (order_id, ordered_at) REFERENCES orders.orders (id, ordered_at)
    )""")
    op.execute("CREATE INDEX saga_pending ON orders.saga_instances (updated_at) WHERE step <> 'DONE'")
    op.execute("""CREATE TABLE orders.idempotency_keys (
        customer_id TEXT NOT NULL, key TEXT NOT NULL, fingerprint TEXT NOT NULL,
        order_id TEXT NOT NULL UNIQUE, response_code INTEGER NULL, response_body JSONB NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY (customer_id, key)
    )""")
    op.execute("""CREATE TABLE orders.outbox (
        event_id TEXT PRIMARY KEY, order_id TEXT NOT NULL, payload JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(), published_at TIMESTAMPTZ NULL
    )""")
    op.execute("CREATE INDEX outbox_pending ON orders.outbox (created_at) WHERE published_at IS NULL")


def downgrade() -> None:
    for table in ("outbox", "idempotency_keys", "saga_instances", "order_lines", "orders"):
        op.execute(f"DROP TABLE orders.{table}")
