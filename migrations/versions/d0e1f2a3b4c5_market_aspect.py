"""material market aspect (Phase 3-2: 산업 카테고리 분석 — 시장 규모·성장/유통 채널 구조/주요 플레이어 지도)

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-11-04 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'd0e1f2a3b4c5'
down_revision = 'c9d0e1f2a3b4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('materials', sa.Column('market_aspect', sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column('materials', 'market_aspect')
