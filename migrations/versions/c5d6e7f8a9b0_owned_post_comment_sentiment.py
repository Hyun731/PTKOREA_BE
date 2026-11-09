"""owned post comment sentiment (피드백 #2: 자사 SNS 댓글 감성 분석)

Revision ID: c5d6e7f8a9b0
Revises: b4c5d6e7f8a9
Create Date: 2026-11-09 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'c5d6e7f8a9b0'
down_revision = 'b4c5d6e7f8a9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('owned_posts', schema=None) as batch_op:
        batch_op.add_column(sa.Column('comment_sentiment', sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('owned_posts', schema=None) as batch_op:
        batch_op.drop_column('comment_sentiment')
