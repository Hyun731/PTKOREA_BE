"""case commentary (P4 사례 카드 해설)

Revision ID: b2c3d4e5f6a7
Revises: a1f2c3d4e5f6
Create Date: 2026-10-28 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'b2c3d4e5f6a7'
down_revision = 'a1f2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('materials', schema=None) as batch_op:
        batch_op.add_column(sa.Column('ai_detail', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('ai_implication', sa.Text(), nullable=True))

    op.create_table(
        'case_commentary',
        sa.Column('id', sa.String(length=40), nullable=False),
        sa.Column('project_id', sa.String(length=40), nullable=False),
        sa.Column('material_id', sa.String(length=40), nullable=False),
        sa.Column('detail', sa.Text(), nullable=True),
        sa.Column('implication', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('errors', sa.JSON(), nullable=False),
        sa.Column('model', sa.String(length=60), nullable=True),
        sa.Column('job_id', sa.String(length=40), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_case_commentary_project_id'), 'case_commentary', ['project_id'], unique=False)
    op.create_index(op.f('ix_case_commentary_material_id'), 'case_commentary', ['material_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_case_commentary_material_id'), table_name='case_commentary')
    op.drop_index(op.f('ix_case_commentary_project_id'), table_name='case_commentary')
    op.drop_table('case_commentary')
    with op.batch_alter_table('materials', schema=None) as batch_op:
        batch_op.drop_column('ai_implication')
        batch_op.drop_column('ai_detail')
