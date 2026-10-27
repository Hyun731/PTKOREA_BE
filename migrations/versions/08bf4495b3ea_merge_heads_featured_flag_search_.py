"""merge heads: featured flag + search channel without naver

Revision ID: 08bf4495b3ea
Revises: 2183cf26f102, cbf6b751ebf1
Create Date: 2026-10-14 08:14:54.183735
"""
from alembic import op
import sqlalchemy as sa


revision = '08bf4495b3ea'
down_revision = ('2183cf26f102', 'cbf6b751ebf1')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
