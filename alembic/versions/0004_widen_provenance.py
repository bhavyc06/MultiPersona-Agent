"""widen_decisions_provenance

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-12
"""
import sqlalchemy as sa
from alembic import op

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade():
    # VARCHAR(20) too short for 'consensus_by_supervisor' (23 chars)
    # and future provenance values. Widen to VARCHAR(50).
    op.alter_column(
        'decisions', 'provenance',
        existing_type=sa.String(20),
        type_=sa.String(50),
        existing_nullable=True,
    )
    # Widen state column for safety (currently VARCHAR(20))
    op.alter_column(
        'decisions', 'state',
        existing_type=sa.String(20),
        type_=sa.String(30),
        existing_nullable=False,
    )


def downgrade():
    pass
