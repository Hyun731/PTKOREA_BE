"""material summary and source text (자료 해석 요약, 원문 보관)

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-10-30 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'e5f6a7b8c9d0'
down_revision = 'd4e5f6a7b8c9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('sources', schema=None) as batch_op:
        batch_op.add_column(sa.Column('text', sa.Text(), nullable=True))
    with op.batch_alter_table('materials', schema=None) as batch_op:
        batch_op.add_column(sa.Column('summary', sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('materials', schema=None) as batch_op:
        batch_op.drop_column('summary')
    with op.batch_alter_table('sources', schema=None) as batch_op:
        batch_op.drop_column('text')
