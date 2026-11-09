"""owned post views (피드백 #2: 자사 SNS 정량 데이터 — 조회수 저장)

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
Create Date: 2026-11-09 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'b4c5d6e7f8a9'
down_revision = 'a3b4c5d6e7f8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('owned_posts', schema=None) as batch_op:
        batch_op.add_column(sa.Column('views', sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('owned_posts', schema=None) as batch_op:
        batch_op.drop_column('views')
