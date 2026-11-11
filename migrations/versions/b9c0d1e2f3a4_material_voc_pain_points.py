"""material VOC pain points (P2-7)

Revision ID: b9c0d1e2f3a4
Revises: a8b9c0d1e2f3
Create Date: 2026-11-11 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "b9c0d1e2f3a4"
down_revision = "a8b9c0d1e2f3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("materials", schema=None) as batch_op:
        batch_op.add_column(sa.Column("voc_pain_points", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))


def downgrade() -> None:
    with op.batch_alter_table("materials", schema=None) as batch_op:
        batch_op.drop_column("voc_pain_points")
