"""P4 사례 카드 해설 검증 규칙 (app/services/case_commentary.py)."""
from app.services.case_commentary import DETAIL_MAX, IMPLICATION_MAX, check_commentary


def test_check_commentary_accepts_clean_text():
    assert check_commentary("협업으로 화제성 확보 — 한정판 출시로 품절 유도", "자사도 한정판 전략으로 초기 관심 환기") == []


def test_check_commentary_rejects_digits():
    errors = check_commentary("3일 만에 완판", "자사도 적용")
    assert any("숫자" in e for e in errors)


def test_check_commentary_rejects_too_long():
    errors = check_commentary("가" * (DETAIL_MAX + 1), "나" * (IMPLICATION_MAX + 1))
    assert any("detail" in e for e in errors) and any("implication" in e for e in errors)


def test_check_commentary_rejects_forbidden_words():
    assert any("확인 필요" in e or "쓸 수 없는" in e for e in check_commentary("확인 필요한 캠페인", "시사점"))


def test_check_commentary_rejects_empty():
    assert check_commentary("", "시사점") != []
    assert check_commentary("해설", "") != []
