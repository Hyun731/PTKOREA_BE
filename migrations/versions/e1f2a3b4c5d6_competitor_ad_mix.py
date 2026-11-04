"""competitor ad mix (Phase 3-2: 경쟁사 포지셔닝 보강 — 유료 소셜 광고 소재 유형 비중)

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
Create Date: 2026-11-04 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'e1f2a3b4c5d6'
down_revision = 'd0e1f2a3b4c5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'competitor_ad_mix',
        sa.Column('id', sa.String(length=40), nullable=False),
        sa.Column('project_id', sa.String(length=40), nullable=False),
        sa.Column('brand_id', sa.String(length=10), nullable=False),
        sa.Column('entity', sa.String(length=120), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('mix', sa.JSON(), nullable=True),
        sa.Column('ad_count', sa.Integer(), nullable=True),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('checked_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_competitor_ad_mix_project_id'), 'competitor_ad_mix', ['project_id'], unique=False)
    op.create_index(op.f('ix_competitor_ad_mix_brand_id'), 'competitor_ad_mix', ['brand_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_competitor_ad_mix_brand_id'), table_name='competitor_ad_mix')
    op.drop_index(op.f('ix_competitor_ad_mix_project_id'), table_name='competitor_ad_mix')
    op.drop_table('competitor_ad_mix')
