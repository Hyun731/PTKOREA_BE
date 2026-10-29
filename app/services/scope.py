"""Research scope: the AE factbook master items in 3C order, and the ResearchPlan built from them.

Every item (팩트북 표준 목차 §2, §4) sits under Company → Competitor → Customer and carries its own
whom / when / where / how many (§3.5). Sensible defaults decide all of it; the planner reads one
direction sentence per item and only asks for a change when it is wrong. Items an existing
collector can run become runnable research items; the rest are planned so a person can fill them
by hand, and say so instead of pretending to collect.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from app.services.catalog import CHANNELS, shift_months
from core.ingestion.csv_import import window_months
from core.schemas.project import Project, ScopeSetting

PARTS = [
    {"id": "company", "no": "1", "label": "자사 분석", "en": "Company",
     "question": "이 브랜드는 누구이고, 무엇을 팔고, 지금 어디까지 왔나"},
    {"id": "competitor", "no": "2", "label": "경쟁사 분석", "en": "Competitor",
     "question": "시장은 어떻고, 경쟁사는 누구이며 무엇으로 이기고 있나"},
    {"id": "customer", "no": "3", "label": "소비자 분석", "en": "Customer",
     "question": "소비자는 이 브랜드를 어떻게 보고, 어디서 알고, 어디서 사나"},
]

# Channels an existing collector actually uses.
AUTO_CHANNELS: dict[str, set[str]] = {
    "owned": {"instagram_owned", "youtube_owned"},
    "influencer": {"instagram", "youtube"},
    "campaign": {"web"},
    "market": {"web"},
    "search": {"search_naver"},
}

# subject: self | competitor | benchmark | market — whom one research item looks at, per self brand.
# collector: the research section that runs it (None = planned, filled by hand; "generated" = made from
# other items' results, no research item). period: "inherit" or months back from the project end.
ITEMS: list[dict] = [
    # ---------------------------------------------------------------- 1. 자사 분석 (Company)
    {"id": "2-1", "part": "company", "group": "기업과 제품", "title": "기업 개요",
     "question": "{brand} 설립일·대표·본사·임직원 수·연혁, 최근 3개 회계연도 매출과 영업이익",
     "subject": "self", "collector": None, "channels": ["dart", "web"], "period": 36,
     "period_hint": "최근 3개 회계연도", "output": "필드 8개 중 6개 이상, 매출 3개년은 DART 출처"},
    {"id": "2-2", "part": "company", "group": "기업과 제품", "title": "대표 약력",
     "question": "{brand} 대표(공동대표면 각각)의 경력", "subject": "self", "collector": None,
     "channels": ["web", "dart"], "period": 36, "output": "대표마다 경력 3줄 + 출처"},
    {"id": "2-3", "part": "company", "group": "기업과 제품", "title": "비전과 제품 라인업",
     "question": "{brand} 서비스(제품)마다 설명·런칭일·매출 구성, 브랜드가 지향하는 바", "subject": "self",
     "collector": None, "channels": ["web", "dart"], "period": 24, "output": "전 서비스 표 + 서비스마다 1장"},
    {"id": "2-4", "part": "company", "group": "기업과 제품", "title": "시장 내 입지 (브랜드 자산 퍼널)",
     "question": "{brand} 인지·고려·보유·선호·NPS, 이용경험률과 기능별 만족률 추이", "subject": "self",
     "collector": None, "channels": ["upload", "app_review"], "period": 12, "period_hint": "최신 1회분 + 전년 비교",
     "uploads": ["자체 패널 조사", "브랜드 트래커"], "output": "지표마다 값·n·국가·측정일"},
    {"id": "2-5", "part": "company", "group": "기업과 제품", "title": "소비자 정의 (타깃 프로필)",
     "question": "{brand} 핵심 타깃은 누구이고 무엇을 원하며 어떤 상황에서 사나", "subject": "self",
     "collector": None, "channels": ["upload", "community"], "period": "inherit",
     "output": "타깃 한 줄 + 니즈 3개 + 근거 원문 2개"},
    {"id": "2-6", "part": "company", "group": "채널과 활동", "title": "Owned 채널 운영 현황",
     "question": "{brand} 공식 Instagram·YouTube 채널 전체 게시물(팔로워·게시 빈도·반응)", "subject": "self",
     "collector": "owned", "templates": ["2-1", "2-2"],
     "channels": ["instagram_owned", "youtube_owned", "naver_blog"], "default_channels": ["instagram_owned", "youtube_owned"],
     "period": "inherit", "period_hint": "권장 최근 6개월", "needs": "브랜드 공식 계정 URL",
     "output": "계정마다 KPI 5개 + 조회일 + 인기 콘텐츠 3건"},
    {"id": "2-7", "part": "company", "group": "채널과 활동", "title": "Earned·Paid 활동 (인플루언서)",
     "question": "{brand} 관련 크리에이터 공개 게시물(조회·반응·게시일)", "subject": "self",
     "collector": "influencer", "templates": ["3-1"], "channels": ["instagram", "youtube", "tiktok", "upload"],
     "default_channels": ["instagram", "youtube"], "period": "inherit", "period_hint": "권장 최근 6개월",
     "uploads": ["내부 매체 리포트"], "output": "인플루언서 원장 행마다 크리에이터·팔로워·조회·반응률"},
    {"id": "2-8", "part": "company", "group": "채널과 활동", "title": "자사 캠페인 아카이브",
     "question": "{brand} 캠페인·활동 사례", "subject": "self", "collector": "campaign", "templates": ["C1", "C2", "1-6"],
     "channels": ["web", "instagram", "youtube", "tvcf"], "default_channels": ["web", "instagram", "youtube"],
     "period": "inherit", "period_hint": "권장 최근 12~24개월", "limit": {"label": "새 사례 카드 상한", "default": 10},
     "output": "캠페인마다 기간·대행사·모델·카피"},
    {"id": "4-1", "part": "company", "group": "주요 이슈", "title": "긍정 이슈",
     "question": "{brand} 신규 기능·비전 발표·서비스 확장·수상·투자 소식", "subject": "self", "collector": None,
     "channels": ["web"], "period": 6, "period_hint": "최근 3~6개월, 최신순", "output": "이슈마다 제목·매체·일자·요약 2줄"},
    {"id": "4-2", "part": "company", "group": "주요 이슈", "title": "리스크 이슈",
     "question": "{brand} 사기·만족도·조직·규제 위반 등 부정 이슈", "subject": "self", "collector": None,
     "channels": ["web", "community"], "default_channels": ["web"], "period": 6, "period_hint": "최근 3~6개월, 최신순",
     "output": "이슈마다 제목·매체·일자·요약 2줄"},
    {"id": "4-3", "part": "company", "group": "주요 이슈", "title": "대응 활동",
     "question": "{brand} 리스크 이슈에 대한 대응(제도 도입·모니터링 강화)", "subject": "self", "collector": None,
     "channels": ["web"], "period": 6, "output": "리스크 이슈와 1:1로 짝지은 대응"},
    # ---------------------------------------------------------------- 2. 경쟁사 분석 (Competitor)
    {"id": "3-1", "part": "competitor", "group": "시장 환경", "title": "산업 현황",
     "question": "{category} 시장·타겟 공식 자료 (시장 규모·성장률)", "subject": "market", "collector": "market",
     "templates": ["M1"], "channels": ["web", "report"], "default_channels": ["web"], "period": "inherit",
     "period_hint": "권장 최근 3년", "output": "수치마다 발표 기관 + 연도"},
    {"id": "3-2", "part": "competitor", "group": "시장 환경", "title": "경쟁 구도 (검색·점유)",
     "question": "{brand}·경쟁사({competitors}) 검색 점유·커머스 랭킹", "subject": "self", "collector": "search",
     "templates": ["2-8a", "2-8b", "2-8c", "2-8d"], "channels": ["search_naver", "search_csv", "commerce_rank", "upload"],
     "default_channels": ["search_naver", "search_csv"], "period": "inherit", "period_hint": "최신 월 + 전년 동월",
     "uploads": ["검색 지수 CSV"], "output": "한 장표에 한 소스, 같은 기준일"},
    {"id": "3-3", "part": "competitor", "group": "시장 환경", "title": "신규 진입자",
     "question": "{category} 최근 새로 들어온 플레이어와 차별점", "subject": "market", "collector": None,
     "channels": ["web"], "period": 12, "output": "플레이어마다 진입 시점·차별점 1줄·출처"},
    {"id": "3-4", "part": "competitor", "group": "시장 환경", "title": "규제와 정책",
     "question": "{category}에 영향을 주는 정책·제도화 움직임", "subject": "market", "collector": None,
     "channels": ["web"], "period": 12, "output": "이슈마다 기관·일자·영향 1줄"},
    {"id": "3-5", "part": "competitor", "group": "경쟁사", "title": "경쟁사 포지셔닝 (3C 비교)",
     "question": "경쟁사 {entity}의 타깃 공략 방식·포지셔닝·미디어 믹스", "subject": "competitor", "collector": None,
     "channels": ["web", "tvcf", "youtube"], "default_channels": ["web"], "period": "inherit",
     "output": "경쟁사마다 Customer·Competitor·Company 각 1~2줄"},
    {"id": "3-6", "part": "competitor", "group": "경쟁사", "title": "경쟁사 BRAND 페이지",
     "question": "경쟁사 {entity}의 슬로건·TVC 카피·공식 문구, 비주얼, 소비자가 읽은 메시지", "subject": "competitor",
     "collector": None, "channels": ["web", "instagram", "youtube", "commerce_review", "community"],
     "default_channels": ["web", "instagram", "youtube"], "period": 24,
     "output": "브랜드 표현 3개 + 비주얼 4컷 + 메시지 vs 인식 3열"},
    {"id": "3-7", "part": "competitor", "group": "경쟁사", "title": "경쟁사 CASE 카드",
     "question": "경쟁사 {entity} 캠페인·활동 사례", "subject": "competitor", "collector": "campaign",
     "templates": ["C1", "C2"], "channels": ["web", "instagram", "youtube", "community"],
     "default_channels": ["web", "instagram", "youtube"], "period": "inherit", "period_hint": "권장 최근 24개월, 브랜드당 3~5건",
     "limit": {"label": "새 사례 카드 상한", "default": 10}, "output": "기간·이미지·성과·진행 방식·원문·관찰"},
    {"id": "3-8", "part": "competitor", "group": "경쟁사", "title": "CASE 묶음 요약",
     "question": "같은 테마의 사례 3건을 한 장에 묶은 공통점", "subject": "competitor", "collector": "generated",
     "channels": [], "period": "inherit", "from": ["3-7"], "output": "테마명 + 카드 3"},
    {"id": "3-9", "part": "competitor", "group": "경쟁사", "title": "유사 카테고리 벤치마크",
     "question": "벤치마크 {entity} 참고 사례 (경쟁 분모 제외)", "subject": "benchmark", "collector": "campaign",
     "templates": ["C1", "C2"], "channels": ["web", "instagram", "youtube"], "period": "inherit",
     "period_hint": "권장 최근 24개월", "limit": {"label": "새 사례 카드 상한", "default": 10},
     "output": "3-7과 같은 카드 + 벤치마크 표기"},
    # ---------------------------------------------------------------- 3. 소비자 분석 (Customer)
    {"id": "5-1", "part": "customer", "group": "소비자 인식", "title": "소비자 인식 원문",
     "question": "{brand}를 믿고 사는 이유와 다른 브랜드로 넘어가는 이유(소비자 원문)", "subject": "self",
     "collector": None, "channels": ["community", "commerce_review", "app_review", "naver_blog"],
     "default_channels": ["community", "commerce_review"], "period": 24, "period_hint": "커뮤니티 표본 확보를 위해 넓게",
     "output": "양쪽 각 원문 4~5개 + 매체 + 일자"},
    {"id": "5-2", "part": "customer", "group": "소비자 인식", "title": "브랜드 인식 경로",
     "question": "{category} 연령대별로 브랜드를 처음 알고 확인하는 곳, 인플루언서·리뷰의 영향", "subject": "market",
     "collector": None, "channels": ["report", "upload"], "period": 12, "period_hint": "최신 조사",
     "uploads": ["브랜드 트래커"], "output": "연령대 × 매체 접점 표 + 조사 기관·연도·n"},
    {"id": "5-3", "part": "customer", "group": "구매 여정", "title": "구매 여정과 이탈 지점",
     "question": "인지 → 탐색 → 검증 → 구매 → 확산 단계마다 접점·상태·끊기는 곳", "subject": "self",
     "collector": "generated", "channels": [], "period": "inherit", "from": ["2-4", "2-6", "3-2", "5-1"],
     "output": "5단 × 접점·상태·보완 방향 표"},
    {"id": "5-4", "part": "customer", "group": "구매 여정", "title": "구매 상황 지도",
     "question": "{category}를 언제, 왜 사고, 그때 무엇을 따지나", "subject": "market", "collector": "generated",
     "channels": [], "period": "inherit", "from": ["5-1"], "output": "구매 계기 × 고려 요소 × 대표 원문"},
    {"id": "6-1", "part": "customer", "group": "채널과 콘텐츠 트렌드", "title": "채널별 콘텐츠 트렌드",
     "question": "{category} 숏폼·AI 활용·라이브·커뮤니티형 등 지금 통하는 콘텐츠 형식과 성공 사례", "subject": "market",
     "collector": None, "channels": ["report", "web"], "period": 12, "output": "트렌드 카드 4장(수치·출처)"},
    {"id": "6-2", "part": "customer", "group": "채널과 콘텐츠 트렌드", "title": "매체 환경과 다음 해 키워드",
     "question": "디지털 광고비 전망, 매체별 비중 변화, 새 매체와 기술", "subject": "market", "collector": None,
     "channels": ["report", "web"], "period": 12, "period_hint": "최근 12개월 + 다음 해 전망",
     "output": "수치 3~5개 + 키워드 3~5"},
]
BY_ID = {s["id"]: s for s in ITEMS}

# Sections the deck reads a window from (metrics, rules, footnotes) and the scope item that sets it.
SECTION_ITEM = {"owned": "2-6", "influencer": "2-7", "campaign": "2-8", "search": "3-2", "market": "3-1"}


def _default_channels(spec: dict) -> list[str]:
    return list(spec.get("default_channels", spec["channels"]))


def automation(spec: dict, channels: list[str]) -> str:
    """auto: a collector runs it with a selected channel · manual: a person fills it · generated."""
    col = spec["collector"]
    if col == "generated":
        return "generated"
    if col and AUTO_CHANNELS.get(col, set()) & set(channels):
        return "auto"
    return "manual"


def catalog() -> dict:
    items = []
    for s in ITEMS:
        items.append({
            "id": s["id"], "part": s["part"], "group": s["group"], "title": s["title"], "question": s["question"],
            "subject": s["subject"], "collector": s["collector"], "templates": s.get("templates", []),
            "channels": s["channels"], "default_channels": _default_channels(s),
            "auto_channels": sorted(AUTO_CHANNELS.get(s["collector"] or "", set()) & set(s["channels"])),
            "period": s["period"], "period_hint": s.get("period_hint"), "limit": s.get("limit"),
            "uploads": s.get("uploads", []), "needs": s.get("needs"), "from": s.get("from", []), "output": s["output"],
        })
    return {"parts": PARTS, "items": items}


def _months_window(end: date, months: int) -> tuple[date, date]:
    return shift_months(end + timedelta(days=1), -months), end  # 6 months to 09-30 starts 04-01


def _default_setting(spec: dict, project: Project) -> ScopeSetting:
    templates = set(spec.get("templates", []))
    enabled = bool(templates & set(project.enabled_slides))
    section = next((sec for sec, iid in SECTION_ITEM.items() if iid == spec["id"]), None)
    w = project.window_for(section) if section else None
    if w and (w.start, w.end) != (project.period.start, project.period.end):  # a window set before scope existed
        return ScopeSetting(item_id=spec["id"], enabled=enabled, period="custom", start=w.start, end=w.end)
    if spec["period"] == "inherit":
        return ScopeSetting(item_id=spec["id"], enabled=enabled)
    return ScopeSetting(item_id=spec["id"], enabled=enabled, period="months", months=spec["period"])


def resolve(project: Project) -> list[dict]:
    """Every catalog item with the planner's setting (or the default) and the actual dates."""
    given = {s.item_id: s for s in project.scope}
    out = []
    for spec in ITEMS:
        s = given.get(spec["id"]) or _default_setting(spec, project)
        if s.period == "custom":
            start, end = s.start, s.end
        elif s.period == "months":
            start, end = _months_window(project.period.end, s.months)
        else:
            start, end = project.period.start, project.period.end
        channels = [c for c in s.channels if c in spec["channels"]] if s.channels is not None else _default_channels(spec)
        limit = spec.get("limit")
        out.append({
            "item_id": spec["id"], "enabled": s.enabled, "period": s.period, "months": s.months,
            "start": start, "end": end, "channels": channels, "targets": s.targets,
            "max_items": (s.max_items or limit["default"]) if limit else None,
            "automation": automation(spec, channels), "focus": s.focus, "keywords": s.keywords,
        })
    return out


def setting_for(project: Project, item_id: Optional[str]) -> Optional[dict]:
    return next((r for r in resolve(project) if r["item_id"] == item_id), None) if item_id else None


def _josa(word: str, pair: tuple[str, str]) -> str:
    """을/를 by whether the last syllable has a final consonant (받침)."""
    last = word.rstrip(" )")[-1:] if word else ""
    has = "가" <= last <= "힣" and (ord(last) - 0xAC00) % 28 != 0
    return word + (pair[0] if has else pair[1])


def _names(xs: list[str]) -> str:
    return "·".join(xs)


def direction(spec: dict, r: dict, project: Project) -> list[str]:
    """What this item will look for, over which dates, where — in sentences the planner can okay at a glance."""
    if spec["collector"] == "generated":
        return [f"{', '.join(BY_ID[i]['title'] for i in spec['from'])} 결과를 묶어 만듭니다. 따로 조사하지 않습니다."]
    pool = {"competitor": [c for b in project.brands for c in b.competitors],
            "benchmark": [x for b in project.brands for x in b.benchmarks]}.get(spec["subject"])
    if pool is not None:
        who = [x for x in dict.fromkeys(pool) if r["targets"] is None or x in r["targets"]]
        if not who:
            return [f"조사할 {'경쟁사' if spec['subject'] == 'competitor' else '벤치마크'}가 없습니다."]
        entity = _names(who)
    else:
        entity = ""
    b0 = project.brands[0]
    what = spec["question"].format(brand=_names([b.name for b in project.brands]), entity=entity,
                                   category=_names(list(dict.fromkeys(c for b in project.brands for c in b.categories)))
                                   or b0.name, competitors=", ".join(b0.competitors))
    lines = [f"{_josa(what, ('을', '를'))} 조사합니다."]
    span = f"{r['start']:%Y.%m.%d} ~ {r['end']:%Y.%m.%d}"
    when = {"inherit": "프로젝트 기간", "months": f"최근 {r['months']}개월", "custom": "지정한 기간"}[r["period"]]
    lines.append(f"{when}({span}) 안의 것만 봅니다.")
    labels = [CHANNELS[c]["label"].split(" (")[0] for c in r["channels"]]
    if r["automation"] == "auto":
        lines.append(f"{', '.join(labels)}에서 자동으로 찾습니다.")
    elif labels:
        lines.append(f"자동 수집기가 없어 {', '.join(labels)} 자료를 직접 넣습니다.")
    else:
        lines.append("고른 수집 채널이 없습니다.")
    if r["max_items"]:
        lines.append(f"대상마다 새 사례 카드는 최대 {r['max_items']}개까지 모읍니다.")
    if spec.get("uploads"):
        lines.append(f"필요한 내부 자료: {', '.join(spec['uploads'])}.")
    if spec.get("needs"):
        lines.append(f"필요한 입력: {spec['needs']}.")
    if r["focus"]:
        lines.append(r["focus"])
    return lines


def validate(project: Project) -> None:
    seen: set[str] = set()
    for s in project.scope:
        spec = BY_ID.get(s.item_id)
        if spec is None:
            raise ValueError(f"조사 범위에 없는 항목입니다: {s.item_id}")
        if s.item_id in seen:
            raise ValueError(f"조사 범위 항목이 중복됩니다: {s.item_id}")
        seen.add(s.item_id)
        bad = set(s.channels or []) - set(spec["channels"])
        if bad:
            raise ValueError(f"{s.item_id} {spec['title']}: 고를 수 없는 채널 {', '.join(sorted(bad))}")


def section_windows(project: Project) -> list[dict]:
    """Windows the deck reads (influencer footnotes, search comparisons), set by the matching scope item."""
    by_id = {r["item_id"]: r for r in resolve(project)}
    out = []
    for section, iid in SECTION_ITEM.items():
        r = by_id[iid]
        if not r["enabled"]:
            continue
        months = window_months(r["start"], r["end"])
        out.append({"section_id": section, "label": f"{months}M" if months else "기간", "start": str(r["start"]),
                    "end": str(r["end"]), "source": "user"})
    return out


def _subjects(spec: dict, brand, targets: Optional[list[str]]) -> list[tuple[str, str]]:
    pick = (lambda names: [n for n in names if targets is None or n in targets])
    if spec["subject"] == "competitor":
        return [(c, "competitor") for c in pick(brand.competitors)]
    if spec["subject"] == "benchmark":
        return [(b, "benchmark") for b in pick(brand.benchmarks)]
    if spec["subject"] == "market":
        return [(brand.categories[0] if brand.categories else brand.name, "market")]
    return [(brand.name, "self")]


def generate_items(project: Project) -> list[dict]:
    """One research item per (self brand × enabled scope item × subject), brand by brand in 3C order."""
    resolved = [(BY_ID[r["item_id"]], r) for r in resolve(project)]
    items: list[dict] = []
    for brand in project.brands:
        category = "·".join(brand.categories) or brand.name
        for spec, r in resolved:
            if not r["enabled"] or spec["collector"] == "generated":
                continue
            for entity, role in _subjects(spec, brand, r["targets"]):
                items.append({
                    "order": len(items) + 1, "brand_id": brand.id, "entity": entity, "role": role,
                    "section_id": spec["collector"] or spec["part"], "scope_id": spec["id"],
                    "question": spec["question"].format(brand=brand.name, entity=entity, category=category,
                                                        competitors=", ".join(brand.competitors)),
                    "period_start": r["start"], "period_end": r["end"], "channels": r["channels"],
                    "required": role == "self" and spec["collector"] is not None,
                })
    return items
