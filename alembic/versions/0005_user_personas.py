"""user_personas (V5-D persona library — save half)

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-24

Per-user library of dynamically recruited experts. Save + display only in
V5-D; the cross-session suggestion logic is deferred.
"""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_personas",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"), nullable=False,
        ),
        sa.Column("role", sa.String(120), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("domain", sa.String(200), nullable=False),
        sa.Column("domain_lock_prompt", sa.Text(), nullable=False, server_default=""),
        sa.Column("default_level", sa.String(8), nullable=False, server_default="L1"),
        sa.Column(
            "source_session_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sessions.id"), nullable=True,
        ),
        sa.Column("use_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("user_id", "role", name="uq_user_persona_user_role"),
    )
    op.create_index("ix_user_personas_user_id", "user_personas", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_user_personas_user_id", table_name="user_personas")
    op.drop_table("user_personas")
