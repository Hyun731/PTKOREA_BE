"""파생 수치(P1-2): 건 단위로 모은 자료를 브랜드 단위 Fact로 바꾼다.

소비자 원문(VOC), 공식 계정 댓글 감성, 커머스 리뷰 스냅샷은 지금까지 표·인용으로만 쓰였다. 여기서
비율·건수 Fact로 바꿔 두면 막대 차트와 헤드라인(fact_ref)이 다른 수치와 똑같이 출처를 달고 쓸 수 있다.

규칙
- 채택된(accepted) 자료만 쓴다. 협찬·체험단 원문은 비율 계산에서 뺀다.
- 비율은 표본 수 n이 `min_n` 미만이면 만들지 않는다(작은 표본의 비율을 장표에 올리지 않기 위해).
  n은 dims["n"]에, 계산 방법은 method에 남는다 — 각주가 "n=○○ · AI 분류"를 붙일 수 있게.
- 같은 입력이면 같은 fact id(content_hash가 값·차원·기간으로 정해짐).
- 리뷰 스냅샷의 평점·리뷰 수는 비율이 아니라 측정값이라 n 기준을 적용하지 않는다.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable, Optional
from urllib.parse import urlparse

from core.ingestion.csv_import import content_hash, fact_id_from_hash
from core.schemas.facts import Fact
from core.schemas.materials import CaseMaterial, OwnedPostRef, ReviewSnapshotRef
from core.schemas.project import Project

SOURCE = "derived"
DEFAULT_MIN_N = 20

# 원문 출처 도메인 → 장표에 쓰는 이름. 여기 없는 곳은 발행처(publisher)나 도메인을 그대로 쓴다.
SITE_LABEL: dict[str, str] = {
    "blog.naver.com": "네이버 블로그", "cafe.naver.com": "네이버 카페", "tistory.com": "티스토리",
    "cafe.daum.net": "다음 카페", "dcinside.com": "디시인사이드", "fmkorea.com": "에펨코리아",
    "theqoo.net": "더쿠", "ruliweb.com": "루리웹", "clien.net": "클리앙", "todayhumor.co.kr": "오늘의유머",
    "ppomppu.co.kr": "뽐뿌", "arca.live": "아카라이브", "x.com": "X", "twitter.com": "X", "threads.net": "Threads",
    "threads.com": "Threads", "kin.naver.com": "지식iN", "youtube.com": "YouTube", "tiktok.com": "TikTok",
}
TOPIC_LABEL = {"price": "가격", "quality": "품질", "design": "디자인", "shipping": "배송", "cs": "AS·고객응대",
               "other": "기타"}
PATH_LABEL = {"ad": "광고", "referral": "지인", "influencer": "인플루언서", "store": "매장", "search": "검색",
              "other": "기타"}
POLARITY_LABEL = {"positive": "긍정", "negative": "부정", "neutral": "중립"}


@dataclass(frozen=True)
class DerivedInputs:
    project: Project
    materials: list[CaseMaterial]
    owned_posts: list[OwnedPostRef]
    reviews: list[ReviewSnapshotRef]
    measured_at: date
    min_n: int = DEFAULT_MIN_N


def site_of(m: CaseMaterial) -> str:
    """The community/portal a VOC card came from, as a reader-facing name."""
    host = (urlparse(m.source.url or "").hostname or "").lower().removeprefix("www.").removeprefix("m.")
    for domain, label in SITE_LABEL.items():
        if host == domain or host.endswith("." + domain):
            return label
    return m.source.publisher or host or "기타"


def _pct(part: int, whole: int) -> Decimal:
    return (Decimal(part) * 100 / Decimal(whole)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def _fact(inp: DerivedInputs, *, brand_id: str, entity: str, metric: str, value: Decimal, unit: str, dims: dict,
          method: str, label: str, locator: Iterable[str] = ()) -> Fact:
    dims = {k: str(v) for k, v in sorted(dims.items())}
    period = inp.project.period
    payload = {"brand": brand_id, "entity": entity, "metric": metric, "value": str(value), "unit": unit, "dims": dims,
               "period": f"{period.start}~{period.end}", "measured_at": inp.measured_at.isoformat(), "source": SOURCE,
               "method": method}
    h = content_hash(payload)
    refs = sorted(set(locator))
    return Fact(id=fact_id_from_hash(h), content_hash=h, brand_id=brand_id, entity=entity, metric=metric, value=value,
                unit=unit, dims=dims, period_start=period.start, period_end=period.end, measured_at=inp.measured_at,
                source=SOURCE, method=method, confidence="verified", verification_status="eligible", label=label,
                source_locator=",".join(refs[:50]) or None)


def _share_facts(inp: DerivedInputs, rows: list[CaseMaterial], key, labels: dict[str, str], *, metric: str,
                 dim: str, method: str, what: str) -> list[Fact]:
    """One percent Fact per category of `key(m)` for each (brand, entity), when n ≥ min_n."""
    out: list[Fact] = []
    groups: dict[tuple[str, str], list[CaseMaterial]] = defaultdict(list)
    for m in rows:
        if key(m) is not None and m.brand_id and m.entity:
            groups[(m.brand_id, m.entity)].append(m)
    for (brand_id, entity), ms in sorted(groups.items()):
        n = len(ms)
        if n < inp.min_n:
            continue
        counts = Counter(key(m) for m in ms)
        for cat, c in sorted(counts.items()):
            name = labels.get(cat, cat)
            out.append(_fact(inp, brand_id=brand_id, entity=entity, metric=metric, value=_pct(c, n), unit="percent",
                             dims={dim: cat, "n": n}, method=method, label=f"{entity} {what} · {name}",
                             locator=(m.id for m in ms if key(m) == cat)))
    return out


def voc_facts(inp: DerivedInputs) -> list[Fact]:
    rows = [m for m in inp.materials if m.section_id == "voc" and m.review_status == "accepted" and not m.voc_sponsored]
    out: list[Fact] = []
    # 부정률: 원문 출처(커뮤니티·포털)별, 그리고 전체.
    classified = [m for m in rows if m.voc_sentiment and m.brand_id and m.entity]
    by_site: dict[tuple[str, str, str], list[CaseMaterial]] = defaultdict(list)
    for m in classified:
        by_site[(m.brand_id, m.entity, site_of(m))].append(m)
        by_site[(m.brand_id, m.entity, "전체")].append(m)
    for (brand_id, entity, site), ms in sorted(by_site.items()):
        n = len(ms)
        if n < inp.min_n:
            continue
        neg = [m for m in ms if m.voc_sentiment == "negative"]
        out.append(_fact(inp, brand_id=brand_id, entity=entity, metric="voc_negative_rate", value=_pct(len(neg), n),
                         unit="percent", dims={"site": site, "n": n},
                         method="채택한 소비자 원문 중 AI가 부정으로 분류한 비율(협찬 제외)",
                         label=f"{entity} 소비자 원문 부정률 · {site}", locator=(m.id for m in neg)))
    out += _share_facts(inp, rows, lambda m: m.voc_topic, TOPIC_LABEL, metric="voc_topic_share", dim="topic",
                        method="채택한 소비자 원문의 AI 주제 분류 비중(협찬 제외)", what="소비자 원문 주제")
    out += _share_facts(inp, rows, lambda m: m.voc_awareness, PATH_LABEL, metric="voc_path_share", dim="path",
                        method="인식 경로가 드러난 채택 원문의 경로 비중(협찬 제외)", what="인식 경로")
    return out


def comment_facts(inp: DerivedInputs) -> list[Fact]:
    """공식 계정 댓글 감성: 게시물별 표본을 (브랜드, 대상, 채널)로 더해 긍정·부정·중립 비율."""
    sums: dict[tuple[str, str, str], Counter] = defaultdict(Counter)
    ids: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for p in inp.owned_posts:
        cs = p.comment_sentiment
        if cs is None or cs.sample_size <= 0:
            continue
        k = (p.brand_id, p.entity, p.channel)
        sums[k].update(positive=cs.positive, negative=cs.negative, neutral=cs.neutral, n=cs.sample_size)
        ids[k].append(p.id)
    out: list[Fact] = []
    for (brand_id, entity, channel), c in sorted(sums.items()):
        n = c["n"]
        if n < inp.min_n or not entity:
            continue
        for pol in ("positive", "negative", "neutral"):
            out.append(_fact(inp, brand_id=brand_id, entity=entity, metric="comment_sentiment_rate",
                             value=_pct(c[pol], n), unit="percent", dims={"channel": channel, "polarity": pol, "n": n},
                             method="공식 계정 게시물 댓글 표본의 AI 감성 분류 비율",
                             label=f"{entity} 댓글 {POLARITY_LABEL[pol]} 비율 · {channel}", locator=ids[(brand_id, entity, channel)]))
    return out


def review_facts(inp: DerivedInputs) -> list[Fact]:
    """채택한 커머스 리뷰 스냅샷의 리뷰 수와 평점(5점 만점으로 환산)."""
    out: list[Fact] = []
    for r in sorted(inp.reviews, key=lambda r: r.id):
        if r.review_status != "accepted" or r.access_status != "ok":
            continue
        dims = {"platform": r.platform, "product": r.product_name}
        if r.review_count is not None:
            out.append(_fact(inp, brand_id=r.brand_id, entity=r.entity, metric="review_count", value=Decimal(r.review_count),
                             unit="count", dims=dims, method=f"{r.platform} 공개 상품 페이지 리뷰 수",
                             label=f"{r.entity} {r.product_name} 리뷰 수 · {r.platform}", locator=[r.id]))
        if r.rating is not None and r.rating_scale:
            value = (Decimal(str(r.rating)) * 5 / Decimal(str(r.rating_scale))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            out.append(_fact(inp, brand_id=r.brand_id, entity=r.entity, metric="review_rating", value=value, unit="rating",
                             dims=dims, method=f"{r.platform} 공개 상품 페이지 평점(5점 만점 환산)",
                             label=f"{r.entity} {r.product_name} 평점 · {r.platform}", locator=[r.id]))
    return out


def derive(inp: DerivedInputs) -> list[Fact]:
    """Every derived Fact for this build, in a stable order."""
    return voc_facts(inp) + comment_facts(inp) + review_facts(inp)


def footnote_label(fact: Fact) -> Optional[str]:
    """'n=124 · AI 분류' style note for a derived percent fact (None for plain measurements)."""
    if fact.source != SOURCE or "n" not in fact.dims:
        return None
    return f"n={fact.dims['n']} · AI 분류"
