"""업종별 리서치 variation (피드백 #1 "최우선" 항목 → 개선 계획 P4-2).

업종마다 리서치를 다르게 하는 값을 한곳에 모은다 — INDUSTRY_TYPES(core/schemas/project.py)와 같은
성격의, 코드로 미리 정해 둔 값이라 프로젝트마다 다시 묻지 않는다.

- keyword_hints: 시장(3-1) 검색에 덧붙일 업종 특화 용어. `reviewed=True`인 업종만 그대로 쓴다.
  검토 전 업종은 app/services/industry_keywords.py 후보 흐름(candidate → 사람이 confirmed)을 거친다 —
  자료 자동 채택 금지 원칙과 같다. 초안의 keyword_hints는 그 흐름의 후보로만 나간다.
- gov_stats: 정부·공공기관 보도자료 검색어(예: "한국관광공사 출입국 통계").
- axis_queries: 5대 축 {market, demand, consumer, policy}별 검색 질의 틀. {category}·{year} 자리에
  브랜드 제품군과 조사 연도가 들어간다. research.build_queries()가 기본 질의 뒤에 덧붙인다.
- key_metrics: 업종 핵심 지표(예: 여행=출입국자 수, 뷰티=재구매율).
- season_calendar: 성수기·대목(예: "07-08 여름 휴가").
- policy_keywords: 업종에 영향을 주는 정책 용어(예: 면세 한도).
- shopping_categories: 제품군 → 네이버쇼핑 최상위 분야 코드(integrations/naver/client.SHOP_TOP_CATEGORIES).
- default_scope_on: 업종 유형(INDUSTRY_TYPES)과 상관없이 기본으로 켜는 조사 항목(app/services/scope.py ID).
  나머지 항목은 원래대로 모두 켜져 있고, 기획자가 언제든 끄고 켤 수 있다.

12개 업종 값은 tools/draft_industry_profiles.py(Perplexity 근거 + Anthropic 정리)로 만든 초안을 읽고
고친 것이다. 사람이 아직 확인하지 않은 값이므로 아래에 'AI 초안 — 사람 검토 필요'로 표시한다.
"""
from __future__ import annotations

from types import MappingProxyType
from typing import Mapping, NamedTuple, Optional

AXES: tuple[str, ...] = ("market", "demand", "consumer", "policy")

_EMPTY: Mapping[str, tuple[str, ...]] = MappingProxyType({})


class IndustryProfile(NamedTuple):
    keyword_hints: tuple[str, ...] = ()
    gov_stats: tuple[str, ...] = ()
    axis_queries: Mapping[str, tuple[str, ...]] = _EMPTY
    key_metrics: tuple[str, ...] = ()
    season_calendar: tuple[str, ...] = ()
    policy_keywords: tuple[str, ...] = ()
    shopping_categories: Mapping[str, str] = MappingProxyType({})
    default_scope_on: tuple[str, ...] = ()
    # keyword_hints를 사람이 확인했는지. False면 keyword_hints는 후보로만 쓰인다.
    reviewed: bool = False


def profile_for(industry: Optional[str]) -> Optional[IndustryProfile]:
    return INDUSTRY_PROFILES.get(industry or "")


def axis_queries(industry: Optional[str], axis: str, *, category: str, year) -> list[str]:
    """업종 프로필의 <axis> 질의 틀에 제품군과 연도를 채운 검색어. 프로필이 없으면 []."""
    profile = profile_for(industry)
    if not profile:
        return []
    out = []
    for template in profile.axis_queries.get(axis, ()):
        q = " ".join(template.format(category=category, year=year).split())
        if q and q not in out:
            out.append(q)
    return out


def _p(**kw) -> IndustryProfile:
    """dict 값을 읽기 전용으로 감싸 만든다(NamedTuple 기본값 공유로 생기는 실수를 막는다)."""
    for key in ("axis_queries", "shopping_categories"):
        if key in kw:
            kw[key] = MappingProxyType(dict(kw[key]))
    return IndustryProfile(**kw)


# ---------------------------------------------------------------------------------------------------
# AI 초안 — 사람 검토 필요 (tools/draft_industry_profiles.py, 2026-11-11).
# reviewed=True는 keyword_hints만 사람이 확인했다는 뜻이다(여행·패션 — 피드백 #1 파일럿). 나머지 값은
# 모든 업종이 초안이다. 확인을 마치면 이 주석과 업종별 reviewed 값을 고친다.
# ---------------------------------------------------------------------------------------------------
INDUSTRY_PROFILES: dict[str, IndustryProfile] = {
    "패션": _p(
        keyword_hints=("패션 트렌드", "신소재", "지속가능 소재", "업사이클링"),
        reviewed=True,
        gov_stats=("통계청 온라인쇼핑동향 의복", "통계청 소매판매액지수 의복", "한국섬유산업연합회 패션산업 통계"),
        axis_queries={
            "market": ("{category} 복종별 성장률 {year}", "{category} 브랜드 점유율 {year}"),
            "demand": ("{category} 간절기 수요 {year}", "{category} 시즌 판매 동향 {year}", "{category} 인기 아이템 {year}"),
            "consumer": ("{category} 구매 요인 {year}", "{category} 사이즈 불만 리뷰 {year}"),
            "policy": ("{category} 친환경 표시 규제 {year}", "{category} 그린워싱 제재 {year}"),
        },
        key_metrics=("국내 패션시장 규모", "복종별 성장률", "온라인 의류 거래액", "재구매율"),
        season_calendar=("03-04 봄 신상품", "09-11 가을·겨울 시즌", "11 블랙프라이데이", "01 겨울 시즌오프"),
        policy_keywords=("친환경 표시·광고", "그린워싱 규제", "EU 기업 지속가능성 실사 지침(CSDDD)"),
        shopping_categories={"의류": "50000000", "가방·신발·액세서리": "50000001", "스포츠·아웃도어 의류": "50000007"},
        default_scope_on=("2-9",),
    ),
    "뷰티": _p(
        keyword_hints=("AI 맞춤형 화장품", "뷰티테크", "더마 코스메틱", "사계절 선케어", "뷰티·웰니스"),
        gov_stats=("식품의약품안전처 화장품 생산실적", "관세청 화장품 수출입 통계", "통계청 온라인쇼핑동향 화장품"),
        axis_queries={
            "market": ("{category} 수출 실적 {year}", "{category} 브랜드 점유율 {year}"),
            "demand": ("{category} 인기 성분 {year}", "{category} 판매 순위 {year}", "{category} 시즌 수요 {year}"),
            "consumer": ("{category} 구매 이유 {year}", "{category} 사용 후기 불만 {year}"),
            "policy": ("{category} 화장품법 개정 {year}", "{category} 안전성 평가 규제 {year}"),
        },
        key_metrics=("화장품 수출액", "재구매율", "리뷰 평점·리뷰 수", "온라인 판매 비중"),
        season_calendar=("03-04 봄 환절기", "06-08 여름 선케어", "11 블랙프라이데이", "12 연말 홀리데이"),
        policy_keywords=("화장품 안전성 평가 의무화", "기능성화장품 심사", "맞춤형화장품 조제관리사"),
        shopping_categories={"스킨케어": "50000002", "색조 메이크업": "50000002", "헤어·바디케어": "50000002",
                             "뷰티 디바이스": "50000003"},
        default_scope_on=("2-9",),
    ),
    "가전·IT": _p(
        keyword_hints=("가전 구독", "AI 가전", "웨어러블", "디지털제품여권"),
        gov_stats=("통계청 온라인쇼핑동향 가전·전자·통신기기", "산업통상부 전자산업 수출입 동향", "한국소비자원 가전 소비자 피해"),
        axis_queries={
            "market": ("{category} 온라인 판매 비중 {year}", "{category} 점유율 {year}"),
            "demand": ("{category} 구독 수요 {year}", "{category} 성수기 수요 {year}"),
            "consumer": ("{category} 구매 고려 요인 {year}", "{category} AS 불만 {year}"),
            "policy": ("{category} 에너지효율 등급 {year}", "{category} 구독 표시 의무 {year}"),
        },
        key_metrics=("품목별 판매액 성장률", "온라인 판매 비중", "평균 판매가격", "상품 리뷰 평점"),
        season_calendar=("01-02 설·혼수", "03 신학기", "06-08 여름 냉방가전", "11 블랙프라이데이"),
        policy_keywords=("가전 구독 총비용 표시", "에너지효율 등급", "고효율 가전 환급", "수리권"),
        shopping_categories={"생활·주방가전": "50000003", "헤드폰·웨어러블": "50000003", "컴퓨터·IT기기": "50000003"},
        default_scope_on=("2-9",),
    ),
    "생활용품": _p(
        keyword_hints=("리필스테이션", "대용량 소분", "친환경 포장재", "가성비 PB 생활용품"),
        gov_stats=("산업통상부 주요 유통업체 매출 동향", "통계청 온라인쇼핑동향", "한국소비자원 소비자불만 동향"),
        axis_queries={
            "market": ("{category} 온라인 매출 {year}", "{category} 업계 점유율 {year}"),
            "demand": ("{category} 인기 품목 {year}", "{category} 대용량 수요 {year}"),
            "consumer": ("{category} 구매 요인 {year}", "{category} 소비자 불만 {year}"),
            "policy": ("{category} 생활화학제품 안전관리 {year}", "{category} 포장재 재활용 규제 {year}"),
        },
        key_metrics=("재구매율", "리뷰 평점·리뷰 수", "온라인 판매 비중", "PB 상품 매출 비중"),
        season_calendar=("설", "03 봄맞이 대청소", "추석", "11 블랙프라이데이"),
        policy_keywords=("생활화학제품 안전확인", "포장재 재활용의무율", "KC 안전인증"),
        shopping_categories={"세제·위생·욕실용품": "50000008", "주방·수납용품": "50000004", "구강·바디케어용품": "50000002"},
        default_scope_on=("2-9",),
    ),
    "식음료": _p(
        keyword_hints=("제로슈거", "저속노화", "헬시플레저", "시즌 한정"),
        gov_stats=("식품의약품안전처 식품 생산실적", "한국농촌경제연구원 식품소비행태조사", "aT 가공식품 세분시장 현황"),
        axis_queries={
            "market": ("{category} 업계 매출 {year}", "{category} 시장 점유율 {year}"),
            "demand": ("{category} 시즌 한정 출시 {year}", "{category} 신제품 인기 {year}"),
            "consumer": ("{category} 구매 이유 조사 {year}", "{category} 맛 리뷰 {year}"),
            "policy": ("{category} 표시 기준 {year}", "{category} 설탕 부담금 {year}"),
        },
        key_metrics=("식품 생산실적", "온라인 음식료품 거래액", "재구매율", "신제품 출시 수"),
        season_calendar=("설", "05 가정의 달", "07-08 여름 음료 성수기", "추석", "12 연말"),
        policy_keywords=("설탕 부담금", "영양표시 의무화", "고카페인 표시"),
        shopping_categories={"가공식품·음료": "50000006", "건강기능식품": "50000008"},
        default_scope_on=("2-9",),
    ),
    "여행": _p(
        keyword_hints=("여행 수요", "출입국자 수", "트래블룩", "고프코어", "그래놀라코어"),
        reviewed=True,
        gov_stats=("한국관광공사 출입국 통계", "문화체육관광부 국민여행조사", "한국문화관광연구원 관광지식정보시스템"),
        axis_queries={
            "market": ("{category} 여행 시장 규모 {year}", "{category} 여행업 점유율 {year}"),
            "demand": ("{category} 해외여행 수요 {year}", "{category} 성수기 여행 수요 {year}"),
            "consumer": ("{category} 여행 구매 결정 요인 {year}", "{category} 여행 소비자 불만 {year}"),
            "policy": ("{category} 면세 한도 {year}", "{category} 관광 지원 정책 {year}"),
        },
        key_metrics=("출입국자 수", "국내여행 경험률", "1인 평균 여행 지출액", "숙박 객실 예약률"),
        season_calendar=("07-08 여름 휴가", "설", "추석", "12 연말 겨울 휴가"),
        policy_keywords=("면세 한도", "근로자 휴가지원사업", "숙박할인권"),
        shopping_categories={"여행가방·캐리어": "50000001", "여행·숙박 상품": "50000009", "캠핑·아웃도어 용품": "50000007"},
        default_scope_on=("3-10", "2-9"),
    ),
    "금융": _p(
        keyword_hints=("생산적 금융", "BDC(기업성장집합투자기구)", "사망보험금 유동화"),
        gov_stats=("한국은행 가계신용 통계", "금융감독원 금융통계정보시스템", "금융위원회 가계대출 동향"),
        axis_queries={
            "market": ("{category} 잔액 추이 {year}", "{category} 은행권 점유율 {year}"),
            "demand": ("{category} 가입 수요 {year}", "{category} 대출 수요 동향 {year}"),
            "consumer": ("{category} 선택 기준 설문 {year}", "{category} 소비자 민원 {year}"),
            "policy": ("{category} 금융위원회 규제 {year}", "{category} 금융제도 변경 {year}"),
        },
        key_metrics=("가계대출 잔액", "연체율", "순이자마진(NIM)", "신규 가입자 수"),
        season_calendar=("01 연말정산", "12 연말 절세 상품 가입"),
        policy_keywords=("가계부채 관리", "기준금리", "주담대 위험가중치"),
        default_scope_on=("3-10",),
    ),
    "플랫폼": _p(
        keyword_hints=("멀티호밍", "슈퍼앱", "배달 수수료 상한제", "입점업체 상생"),
        gov_stats=("공정거래위원회 온라인 플랫폼 실태조사", "통계청 온라인쇼핑동향", "고용노동부 플랫폼종사자 실태조사"),
        axis_queries={
            "market": ("{category} 거래액 순위 {year}", "{category} 플랫폼 점유율 {year}"),
            "demand": ("{category} 앱 MAU 추이 {year}", "{category} 이용량 시즌 {year}"),
            "consumer": ("{category} 앱 선택 이유 {year}", "{category} 이용자 불만 {year}"),
            "policy": ("{category} 플랫폼 규제 법안 {year}", "{category} 수수료 규제 {year}"),
        },
        key_metrics=("월간 활성 이용자 수(MAU)", "거래액(GMV)", "중개 수수료율", "ARPU"),
        season_calendar=("설", "추석", "11 블랙프라이데이", "12 연말 쇼핑"),
        policy_keywords=("온라인 플랫폼 공정화법", "플랫폼 경쟁촉진법", "배달 수수료 상한제"),
        default_scope_on=("3-10",),
    ),
    "통신": _p(
        keyword_hints=("알뜰폰", "5G 중간요금제", "eSIM", "온라인 전용 요금제"),
        gov_stats=("과학기술정보통신부 무선통신서비스 가입 현황", "과학기술정보통신부 무선데이터 트래픽 통계",
                   "통계청 가계동향조사 통신비"),
        axis_queries={
            "market": ("{category} 가입자 점유율 {year}", "{category} ARPU {year}"),
            "demand": ("{category} 번호이동 현황 {year}", "{category} 가입자 추이 {year}"),
            "consumer": ("{category} 요금제 선택 이유 {year}", "{category} 소비자 불만 {year}"),
            "policy": ("{category} 단통법 폐지 영향 {year}", "{category} 가계통신비 정책 {year}"),
        },
        key_metrics=("무선 가입 회선 수", "ARPU", "5G 가입자 비중", "번호이동 건수"),
        season_calendar=("02-03 신학기·플래그십 출시", "07-08 폴더블폰 출시", "10 아이폰 출시"),
        policy_keywords=("단통법 폐지", "알뜰폰 도매제공", "가계통신비 경감"),
        default_scope_on=("3-10",),
    ),
    "자동차": _p(
        keyword_hints=("SDV(소프트웨어 중심 자동차)", "하이브리드 전환", "레벨4 자율주행"),
        gov_stats=("국토교통부 자동차 등록현황", "산업통상부 자동차산업 동향", "환경부 친환경차 보급 계획"),
        axis_queries={
            "market": ("{category} 내수 판매량 {year}", "{category} 시장 점유율 {year}"),
            "demand": ("{category} 친환경차 수요 {year}", "{category} 월별 판매 {year}"),
            "consumer": ("{category} 구매 고려 요인 {year}", "{category} 결함 불만 {year}"),
            "policy": ("{category} 전기차 보조금 {year}", "{category} 개별소비세 {year}"),
        },
        key_metrics=("내수 판매량", "수출액", "누적 등록 대수", "친환경차 등록 비중"),
        season_calendar=("01 신년 프로모션", "03 봄 신차 출시", "06 상반기 결산 프로모션", "12 연말 재고 할인"),
        policy_keywords=("전기차 구매 보조금", "개별소비세 인하", "자율주행자동차법"),
        default_scope_on=("3-10",),
    ),
    "제약": _p(
        keyword_hints=("제네릭 약가인하", "희귀질환 치료제 신속등재", "기술수출"),
        gov_stats=("식품의약품안전처 의약품 생산실적", "한국보건산업진흥원 의약품 수출입 통계", "건강보험심사평가원 의약품 청구 현황"),
        axis_queries={
            "market": ("{category} 생산실적 {year}", "{category} 수출액 {year}"),
            "demand": ("{category} 원외처방 실적 {year}", "{category} 수요 증가 {year}"),
            "consumer": ("{category} 구매 요인 {year}", "{category} 복용 불만 {year}"),
            "policy": ("{category} 약가인하 {year}", "{category} 급여 등재 {year}"),
        },
        key_metrics=("의약품 생산실적", "의약품 수출액", "원외처방 조제액", "R&D 투자 비중"),
        season_calendar=("10-02 독감 유행기", "03-05 환절기 알레르기"),
        policy_keywords=("약가제도 개편", "건강보험 급여 등재", "신속 허가"),
        shopping_categories={"건강기능식품·의약외품": "50000008"},
        default_scope_on=("3-10",),
    ),
    "기타": _p(
        gov_stats=("국가데이터처 온라인쇼핑동향조사", "국가데이터처 서비스업동향조사"),
        axis_queries={
            "demand": ("{category} 수요 동향 {year}", "{category} 판매량 추이 {year}"),
            "consumer": ("{category} 구매 요인 {year}", "{category} 소비자 불만 {year}"),
        },
        key_metrics=("온라인 거래액", "리뷰 평점", "재구매율"),
    ),
}
