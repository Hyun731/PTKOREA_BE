"""업종별 리서치 variation (피드백 #1 "최우선" 항목, 하이브리드 설계).

주요 업종은 사람이 직접 키워드 힌트(시장·카테고리 수요 검색에 덧붙일 업종 특화 용어)와 정부
통계 소스를 정의해 둔다 — INDUSTRY_TYPES(core/schemas/project.py)와 같은 성격의, 코드로 미리
확인해 둔 값이라 프로젝트마다 다시 확인할 필요가 없다. 여기 없는 업종은
app/services/industry_keywords.py가 AI 후보를 제안하고, 사람이 확인해야(candidate→confirmed)
검색에 쓰인다(자료 자동 채택 금지 원칙과 동일).

gov_stats는 아직 파일럿 하나(여행 = 출입국통계)만 연동돼 있다 — integrations/gov_stats/의 모듈
이름을 그대로 적는다. 연동되지 않은 업종은 빈 튜플로 둔다.
"""
from __future__ import annotations

from typing import NamedTuple


class IndustryProfile(NamedTuple):
    keyword_hints: tuple[str, ...] = ()
    gov_stats: tuple[str, ...] = ()


# 핸드오프 예시("여행 관련 패션 브랜드")를 파일럿으로 먼저 채운다. core.schemas.project.INDUSTRIES의
# 나머지 업종은 아직 프로필이 없어 AI 후보 제안으로 대신한다 — 필요해지면 여기에 추가하면 된다.
INDUSTRY_PROFILES: dict[str, IndustryProfile] = {
    "여행": IndustryProfile(
        keyword_hints=("여행 수요", "출입국자 수", "트래블룩", "고프코어", "그래놀라코어"),
        gov_stats=("immigration_arrivals",),
    ),
    "패션": IndustryProfile(
        keyword_hints=("패션 트렌드", "신소재", "지속가능 소재", "업사이클링"),
    ),
}
