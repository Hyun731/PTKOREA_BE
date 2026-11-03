"""owned post entity (Phase 1-1: run_owned_item도 경쟁사 공식 계정을 수집)

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-11-04 00:00:00.000000
"""
import json

from alembic import op
import sqlalchemy as sa


revision = 'a7b8c9d0e1f2'
down_revision = 'f6a7b8c9d0e1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('owned_posts', sa.Column('entity', sa.String(length=120), nullable=False, server_default=''))
    # Backfill: every existing row predates competitor collection, so it is the self brand's own post.
    posts = sa.table('owned_posts', sa.column('id', sa.String), sa.column('project_id', sa.String),
                     sa.column('brand_id', sa.String), sa.column('entity', sa.String))
    projects = sa.table('projects', sa.column('id', sa.String), sa.column('config', sa.JSON))
    conn = op.get_bind()
    names: dict[tuple[str, str], str] = {}
    for row in conn.execute(sa.select(projects.c.id, projects.c.config)):
        cfg = row.config if isinstance(row.config, dict) else json.loads(row.config)
        for b in cfg.get('brands', []):
            names[(row.id, b['id'])] = b['name']
    for row in conn.execute(sa.select(posts.c.id, posts.c.project_id, posts.c.brand_id)):
        name = names.get((row.project_id, row.brand_id))
        if name:
            conn.execute(posts.update().where(posts.c.id == row.id).values(entity=name))


def downgrade() -> None:
    op.drop_column('owned_posts', 'entity')
