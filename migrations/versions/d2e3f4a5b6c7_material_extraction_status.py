"""material extraction status (요약·추출은 자료를 열거나 채택할 때)

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-11-12 12:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "d2e3f4a5b6c7"
down_revision = "c1d2e3f4a5b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # NULL = 예전 방식으로 이미 추출됨(또는 추출 대상 아님), "pending" = 원문만 있고 아직 추출 전, "done", "failed"
    with op.batch_alter_table("materials", schema=None) as batch_op:
        batch_op.add_column(sa.Column("extraction_status", sa.String(length=10), nullable=True))
    # 예전 수집에서 AI가 '관련성 낮음'으로 본 검토 전 자료는 새 규칙대로 숨긴다(선별 제외).
    op.execute("UPDATE materials SET review_status = 'excluded', review_reason = '선별 제외: ' || review_reason "
               "WHERE review_status = 'candidate' AND review_reason LIKE 'AI 판단: 관련성 낮음%'")


def downgrade() -> None:
    op.execute("UPDATE materials SET review_status = 'candidate', review_reason = substr(review_reason, 8) "
               "WHERE review_status = 'excluded' AND review_reason LIKE '선별 제외: AI 판단: 관련성 낮음%'")
    with op.batch_alter_table("materials", schema=None) as batch_op:
        batch_op.drop_column("extraction_status")
