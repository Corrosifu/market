"""Crée les identités locales dans le seul schéma auth."""
import sqlalchemy as sa
from alembic import op

revision = "0001_users"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("email", sa.String(254), nullable=False, unique=True),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.CheckConstraint("role IN ('client', 'seller', 'ops')", name="users_role"),
        schema="auth",
    )


def downgrade() -> None:
    op.drop_table("users", schema="auth")
