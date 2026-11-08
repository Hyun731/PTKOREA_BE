"""피드백 #1(업종별 variation) 하이브리드 설계: 프로필 있는 업종은 그대로, 없는 업종은 AI 후보
→ 확정(confirmed)해야 시장 조사(3-1) 검색에 쓰인다(자동 채택 금지 원칙과 동일)."""
from app.services import industry_keywords
from core.schemas.project import Brand


def _brand(**kw) -> Brand:
    data = {"id": "B1", "name": "샘소나이트", "competitors": ["리모와"]}
    data.update(kw)
    return Brand.model_validate(data)


def test_keyword_hints_uses_the_curated_profile_when_one_exists():
    b = _brand(industry="여행")
    hints = b.keyword_hints()
    assert "트래블룩" in hints and "출입국자 수" in hints


def test_keyword_hints_ignores_candidates_without_confirmation():
    b = _brand(industry="금융", industry_keywords=[{"text": "핀테크", "status": "candidate"}])
    assert b.keyword_hints() == []  # 확정 전엔 검색에 안 쓴다


def test_keyword_hints_uses_confirmed_candidates():
    b = _brand(industry="금융", industry_keywords=[{"text": "핀테크", "status": "confirmed"},
                                                  {"text": "마이데이터", "status": "candidate"}])
    assert b.keyword_hints() == ["핀테크"]


def test_keyword_hints_empty_without_industry_or_profile():
    assert _brand(industry=None).keyword_hints() == []
    assert _brand(industry="금융").keyword_hints() == []  # 프로필도 후보도 없음


def test_missing_is_false_for_industries_with_a_curated_profile():
    assert industry_keywords.missing({"industry": "여행"}) is False
    assert industry_keywords.missing({"industry": "패션"}) is False


def test_missing_is_true_only_once_until_candidates_exist():
    assert industry_keywords.missing({"industry": "금융"}) is True
    assert industry_keywords.missing({"industry": "금융", "industry_keywords": [{"text": "핀테크", "status": "candidate"}]}) is False
    assert industry_keywords.missing({"industry": None}) is False
