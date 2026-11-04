"""review snapshots and keywords (Phase 2: 커머스 리뷰 모듈)

Revision ID: a3b4c5d6e7f8
Revises: f2a3b4c5d6e7
Create Date: 2026-11-04 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'a3b4c5d6e7f8'
down_revision = 'f2a3b4c5d6e7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'review_snapshots',
        sa.Column('id', sa.String(length=40), nullable=False),
        sa.Column('project_id', sa.String(length=40), nullable=False),
        sa.Column('brand_id', sa.String(length=10), nullable=False),
        sa.Column('entity', sa.String(length=120), nullable=False),
        sa.Column('role', sa.String(length=20), nullable=False),
        sa.Column('platform', sa.String(length=20), nullable=False),
        sa.Column('product_name', sa.String(length=300), nullable=False),
        sa.Column('product_url', sa.Text(), nullable=False),
        sa.Column('access_status', sa.String(length=20), nullable=False),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('rating', sa.Float(), nullable=True),
        sa.Column('rating_scale', sa.Float(), nullable=False),
        sa.Column('review_count', sa.Integer(), nullable=True),
        sa.Column('sponsored_count', sa.Integer(), nullable=False),
        sa.Column('measured_at', sa.Date(), nullable=False),
        sa.Column('review_status', sa.String(length=20), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_review_snapshots_project_id'), 'review_snapshots', ['project_id'], unique=False)
    op.create_index(op.f('ix_review_snapshots_brand_id'), 'review_snapshots', ['brand_id'], unique=False)
    op.create_table(
        'review_keywords',
        sa.Column('id', sa.String(length=40), nullable=False),
        sa.Column('snapshot_id', sa.String(length=40), nullable=False),
        sa.Column('sentiment', sa.String(length=10), nullable=False),
        sa.Column('keyword', sa.String(length=100), nullable=False),
        sa.Column('sample_size', sa.Integer(), nullable=False),
        sa.Column('method', sa.Text(), nullable=False),
        sa.Column('quotes', sa.JSON(), nullable=False),
        sa.Column('blocks_purchase', sa.Boolean(), nullable=False),
        sa.Column('review_status', sa.String(length=20), nullable=False),
        sa.ForeignKeyConstraint(['snapshot_id'], ['review_snapshots.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_review_keywords_snapshot_id'), 'review_keywords', ['snapshot_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_review_keywords_snapshot_id'), table_name='review_keywords')
    op.drop_table('review_keywords')
    op.drop_index(op.f('ix_review_snapshots_brand_id'), table_name='review_snapshots')
    op.drop_index(op.f('ix_review_snapshots_project_id'), table_name='review_snapshots')
    op.drop_table('review_snapshots')
