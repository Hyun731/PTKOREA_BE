"""owned posts (2-4 브랜드별 상위 게시물)

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-10-29 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'c3d4e5f6a7b8'
down_revision = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'owned_posts',
        sa.Column('id', sa.String(length=40), nullable=False),
        sa.Column('project_id', sa.String(length=40), nullable=False),
        sa.Column('brand_id', sa.String(length=10), nullable=False),
        sa.Column('channel', sa.String(length=20), nullable=False),
        sa.Column('post_id', sa.String(length=100), nullable=False),
        sa.Column('url', sa.String(length=500), nullable=True),
        sa.Column('posted_at', sa.Date(), nullable=True),
        sa.Column('likes', sa.Integer(), nullable=True),
        sa.Column('comments', sa.Integer(), nullable=True),
        sa.Column('asset_id', sa.String(length=40), nullable=True),
        sa.Column('research_item_id', sa.String(length=40), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('project_id', 'channel', 'post_id', name='uq_owned_posts_project_channel_post'),
    )
    op.create_index(op.f('ix_owned_posts_project_id'), 'owned_posts', ['project_id'], unique=False)
    op.create_index(op.f('ix_owned_posts_brand_id'), 'owned_posts', ['brand_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_owned_posts_brand_id'), table_name='owned_posts')
    op.drop_index(op.f('ix_owned_posts_project_id'), table_name='owned_posts')
    op.drop_table('owned_posts')
