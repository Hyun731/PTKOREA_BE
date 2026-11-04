"""synthesis runs (Phase 3-1: 종합 장표 유형·브랜드별·버전)

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-11-04 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'c9d0e1f2a3b4'
down_revision = 'b8c9d0e1f2a3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'synthesis_runs',
        sa.Column('id', sa.String(length=40), nullable=False),
        sa.Column('project_id', sa.String(length=40), nullable=False),
        sa.Column('brand_id', sa.String(length=10), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('types', sa.JSON(), nullable=False),
        sa.Column('data', sa.JSON(), nullable=False),
        sa.Column('instruction', sa.Text(), nullable=False),
        sa.Column('dropped', sa.JSON(), nullable=False),
        sa.Column('body_fingerprint', sa.String(length=64), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_synthesis_runs_project_id'), 'synthesis_runs', ['project_id'], unique=False)
    op.create_index(op.f('ix_synthesis_runs_brand_id'), 'synthesis_runs', ['brand_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_synthesis_runs_brand_id'), table_name='synthesis_runs')
    op.drop_index(op.f('ix_synthesis_runs_project_id'), table_name='synthesis_runs')
    op.drop_table('synthesis_runs')
