"""session_status_enum

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-02

Replace the free-form 'pending' default on sessions.status with the
SessionStatus enum's initial state ('clarifying') and add a CHECK
constraint ensuring only valid enum values are stored.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_VALID = ("clarifying", "ready", "running", "completed", "failed")
_CHECK_NAME = "ck_sessions_status_enum"


def upgrade() -> None:
    # Migrate existing 'pending' rows to 'clarifying' before adding the constraint
    op.execute("UPDATE sessions SET status = 'clarifying' WHERE status = 'pending'")

    op.alter_column(
        "sessions",
        "status",
        server_default="clarifying",
        existing_type=sa.String(20),
        existing_nullable=False,
    )

    op.create_check_constraint(
        _CHECK_NAME,
        "sessions",
        f"status IN {_VALID}",
    )


def downgrade() -> None:
    op.drop_constraint(_CHECK_NAME, "sessions", type_="check")
    op.alter_column(
        "sessions",
        "status",
        server_default="pending",
        existing_type=sa.String(20),
        existing_nullable=False,
    )
