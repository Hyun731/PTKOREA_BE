"""search channel without naver

Revision ID: 2183cf26f102
Revises: bfe4cc9928f0
Create Date: 2026-10-14 07:35:51.222756
"""
from alembic import op
import sqlalchemy as sa


revision = '2183cf26f102'
down_revision = 'bfe4cc9928f0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Naver DataLab is not available: search items keep only the "own search CSV" channel.
    items = sa.table("research_items", sa.column("id", sa.String), sa.column("channels", sa.JSON))
    conn = op.get_bind()
    for row in conn.execute(sa.select(items.c.id, items.c.channels)):
        chans = row.channels or []
        if "naver_datalab" in chans:
            new = ["search_csv" if c == "naver_datalab" else c for c in chans]
            conn.execute(items.update().where(items.c.id == row.id).values(channels=new))


def downgrade() -> None:
    items = sa.table("research_items", sa.column("id", sa.String), sa.column("channels", sa.JSON))
    conn = op.get_bind()
    for row in conn.execute(sa.select(items.c.id, items.c.channels)):
        if "search_csv" in (row.channels or []):
            conn.execute(items.update().where(items.c.id == row.id)
                         .values(channels=["naver_datalab" if c == "search_csv" else c for c in row.channels]))
