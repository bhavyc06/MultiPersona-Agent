"""v3_schema

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-08

Add v3.0 tables (decisions, challenge_rounds) and new columns
on sessions and agent_messages needed for LangGraph group-chat.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── sessions: three new nullable columns ─────────────────────────────
    op.add_column("sessions",
        sa.Column("roster", postgresql.ARRAY(sa.Text()), nullable=True))
    op.add_column("sessions",
        sa.Column("enriched_problem", sa.Text(), nullable=True))
    op.add_column("sessions",
        sa.Column("termination_reason", sa.String(50), nullable=True))

    # ── agent_messages: is_private flag ──────────────────────────────────
    op.add_column("agent_messages",
        sa.Column("is_private", sa.Boolean(),
                  nullable=False, server_default=sa.text("false")))

    # ── decisions ────────────────────────────────────────────────────────
    op.create_table(
        "decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("session_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("proposed_by", sa.String(100), nullable=False),
        sa.Column("state", sa.String(20), nullable=False, server_default="proposed"),
        sa.Column("provenance", sa.String(20), nullable=True),
        sa.Column("supersedes_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("decisions.id"), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()")),
    )

    # ── challenge_rounds ──────────────────────────────────────────────────
    op.create_table(
        "challenge_rounds",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("decision_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("decisions.id"), nullable=False),
        sa.Column("challenger", sa.String(100), nullable=False),
        sa.Column("round_number", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.String(20), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()")),
    )


def downgrade() -> None:
    op.drop_table("challenge_rounds")
    op.drop_table("decisions")
    op.drop_column("agent_messages", "is_private")
    op.drop_column("sessions", "termination_reason")
    op.drop_column("sessions", "enriched_problem")
    op.drop_column("sessions", "roster")
