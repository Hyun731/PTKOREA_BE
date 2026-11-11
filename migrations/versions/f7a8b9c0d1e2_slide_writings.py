"""slide writings (P3-4: 덱을 만들 때 AI가 쓴 헤드라인·인사이트를 장마다 보관)

Revision ID: f7a8b9c0d1e2
Revises: c5d6e7f8a9b0
Create Date: 2026-11-11 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'f7a8b9c0d1e2'
down_revision = 'c5d6e7f8a9b0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'slide_writings',
        sa.Column('id', sa.String(length=40), nullable=False),
        sa.Column('project_id', sa.String(length=40), nullable=False),
        sa.Column('slide_id', sa.String(length=80), nullable=False),
        sa.Column('kind', sa.String(length=20), nullable=False),
        sa.Column('body_fp', sa.String(length=64), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('data', sa.JSON(), nullable=False),
        sa.Column('errors', sa.JSON(), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('model', sa.String(length=60), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('project_id', 'slide_id', 'kind', name='uq_slide_writing'),
    )
    with op.batch_alter_table('slide_writings', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_slide_writings_project_id'), ['project_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('slide_writings', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_slide_writings_project_id'))
    op.drop_table('slide_writings')
