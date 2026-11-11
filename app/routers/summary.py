"""자료 확인 화면의 요약 탭(P3-2): 자사 분석 / 경쟁사 비교. 읽기 전용 — 새 수집은 하지 않는다."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.routers.projects import get_project
from app.services.owned_summary import summary

router = APIRouter()


@router.get("/projects/{project_id}/owned-summary")
def owned_summary(project_id: str, brand_id: Optional[str] = None, db: Session = Depends(get_db)):
    """자사 브랜드 하나(brand_id, 없으면 첫 브랜드)와 그 경쟁사의 채널별 지표·월별 게시·댓글 감성·페인 포인트·
    블로그 문서 유형·언급량. 값마다 status(candidate|eligible|derived)를 붙여 확인 전 값도 구분해 보여준다."""
    return summary(db, get_project(db, project_id), brand_id)
