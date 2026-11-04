"""material voc fields (Phase 1-3: 소비자 원문 자동 수집)

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-11-04 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'b8c9d0e1f2a3'
down_revision = 'a7b8c9d0e1f2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('materials', sa.Column('voc_sentiment', sa.String(length=10), nullable=True))
    op.add_column('materials', sa.Column('voc_topic', sa.String(length=10), nullable=True))
    op.add_column('materials', sa.Column('voc_awareness', sa.String(length=10), nullable=True))
    op.add_column('materials', sa.Column('voc_sponsored', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column('materials', 'voc_sponsored')
    op.drop_column('materials', 'voc_awareness')
    op.drop_column('materials', 'voc_topic')
    op.drop_column('materials', 'voc_sentiment')
