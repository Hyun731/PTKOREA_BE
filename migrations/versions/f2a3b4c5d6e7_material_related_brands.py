"""material related brand ids (Phase 3-3: 사례 귀속 정리 — 캠페인 자료는 주 대상 브랜드 하나에만 붙고,
함께 등장하는 다른 자사 브랜드는 related_brand_ids로만 연결)

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-11-04 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'f2a3b4c5d6e7'
down_revision = 'e1f2a3b4c5d6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('materials', sa.Column('related_brand_ids', sa.JSON(), nullable=True))
    op.execute("UPDATE materials SET related_brand_ids = '[]' WHERE related_brand_ids IS NULL")


def downgrade() -> None:
    op.drop_column('materials', 'related_brand_ids')
