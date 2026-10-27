"""Synthetic verification input for the 8 representative templates (QUALITY_BASELINE 2).

Volume and text length are modelled on Samsonite PDF p.26/27/29/40/54/68/89/104, but every
brand, value, image and URL here is synthetic (example.com URLs, generated images). Nothing
is transcribed from the reference as a Fact.
"""
from __future__ import annotations

import json
import random
from datetime import date
from decimal import Decimal
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from core.composition.tokens import FONTS_DIR
from core.ingestion.acceptance import accept_facts, accept_posts
from core.ingestion.csv_import import import_facts_csv, import_posts_csv
from core.ingestion.manual import make_manual_fact
from core.schemas.materials import AssetRef, CaseMaterial, ClaimRef, SourceRef
from core.schemas.project import load_project
from core.schemas.slidespec import Crop, Part

BRANDS = [
    ("B1", "브랜드A", ["누리볼트", "한결나덕", "다온리모", "코어딕스"], "러기지", (35, None, "all", "35세 이상 · 전체 성별")),
    ("B2", "브랜드B", ["가람오일", "노을페이스 백팩", "새벽스포츠", "마루헨제이"], "데일리 백팩·가방", (13, 29, "all", "Z세대 13~29세 · 전체")),
    ("B3", "브랜드C", ["누리볼트", "마루헨제이", "로우온", "하늘지오그래픽"], "여행·패션", (19, 29, "female", "여성 19~29세")),
]
SHARES = {  # 12M, 9M, T  (entity order = self + competitors)
    "B1": ([258, 235, 206, 143, 94], [251, 246, 204, 160, 139], [271, 204, 190, 175, 160]),
    "B2": ([22, 197, 184, 164, 133], [22, 201, 190, 170, 150], [12, 357, 220, 210, 201]),
    "B3": ([288, 181, 141, 112, 88], [279, 240, 150, 120, 90], [294, 228, 180, 160, 138]),
}
CATS = {"B1": {"캐리어": ([169, 340, 230, 151, 110], [179, 340, 210, 150, 121]), "백팩": ([501, 180, 130, 110, 79], [480, 190, 140, 110, 80])},
        "B3": {"백팩": ([135, 435, 232, 120, 78], [48, 300, 252, 230, 170])}}


def _csv_row(brand, entity, metric, value, dims, period):
    d = json.dumps(dims, ensure_ascii=False).replace('"', '""')
    return f'{brand},{entity},{metric},{value},index,"{d}",{period},2026-10-01,synthetic_fixture,,합성 품질 검증 자료,verified\n'


def project_json() -> dict:
    brands = []
    for bid, name, comps, cat, (amin, amax, gender, label) in BRANDS:
        brands.append({"id": bid, "name": name, "aliases": [], "categories": [cat],
                       "target": {"age_min": amin, "age_max": amax, "gender": gender, "label": label},
                       "competitors": comps, "keyword_groups": [], "official_profiles": []})
    return {"name": "대표 장표 품질 검증 덱", "client": "합성 품질 검증", "timezone": "Asia/Seoul",
            "period": {"start": "2026-01-01", "end": "2026-09-30"}, "brands": brands,
            "enabled_slides": ["cover", "index", "divider", "2-8a", "2-8b", "2-8d", "3-1", "C1", "5-recap", "A-source", "end"],
            "template_version": "1.0"}


def facts_csv() -> str:
    text = "brand,entity,metric,value,unit,dims,period,measured_at,source,url,method,confidence\n"
    rnd = random.Random(7)
    for bid, name, comps, _, _ in BRANDS:
        ents = [name, *comps]
        s12, s9, st = SHARES[bid]
        for e, v in zip(ents, s12):
            text += _csv_row(bid, e, "search_group_sum", v, {"window": "12M", "seg": "all", "scale_id": f"{bid}-12M"}, "2025-10-01~2026-09-30")
        for e, v in zip(ents, s9):
            text += _csv_row(bid, e, "search_group_sum", v, {"window": "9M", "seg": "all", "scale_id": f"{bid}-9M"}, "2026-01-01~2026-09-30")
        for e, v in zip(ents, st):
            text += _csv_row(bid, e, "search_group_sum", v, {"window": "9M", "seg": "T", "scale_id": f"{bid}-9M-T"}, "2026-01-01~2026-09-30")
        for cat, (all_v, t_v) in CATS.get(bid, {}).items():
            for e, v in zip(ents, all_v):
                text += _csv_row(bid, e, "search_group_sum", v, {"window": "9M", "seg": "all", "scale_id": f"{bid}-{cat}", "cat": cat}, "2026-01-01~2026-09-30")
            for e, v in zip(ents, t_v):
                text += _csv_row(bid, e, "search_group_sum", v, {"window": "9M", "seg": "T", "scale_id": f"{bid}-{cat}-T", "cat": cat}, "2026-01-01~2026-09-30")
        base = {e: v for e, v in zip(ents, s9)}
        for m in range(1, 10):
            for i, e in enumerate(ents):
                trend = 1 + (0.06 * (m - 5) if i == 1 else -0.03 * (m - 5) if i == 0 else 0.01 * rnd.uniform(-3, 3))
                if bid == "B2" and e == comps[2] and m == 5:
                    continue  # missing month must stay a visible gap
                v = round(base[e] / 3 * trend + rnd.uniform(-4, 4), 1)
                text += _csv_row(bid, e, "search_index_monthly", v, {"month": f"2026-{m:02d}", "seg": "all", "scale_id": f"{bid}-monthly"}, "2026-01-01~2026-09-30")
    return text


POSTS = [
    ("Q1a", "youtube", "합성채널 산책TV", 1270000, "2026-02-03", 195870, 790, 91, "가벼운 백팩 3종"),
    ("Q1b", "youtube", "합성채널 출근일기", 198000, "2026-02-14", 151160, 4300, 312, "가벼운 백팩 3종"),
    ("Q1c", "youtube", "합성채널 직장인로그", 76000, "2026-03-02", 145545, 2050, 154, "가벼운 백팩 3종"),
    ("Q1d", "youtube", "합성채널 골목인터뷰", 384000, "2026-03-20", 80549, 610, 82, "26SS 비즈니스"),
    ("Q1e", "instagram", "합성 웹툰작가", 1241000, "2026-03-25", None, 3300, 300, "경량 백팩"),
    ("Q2a", "youtube", "합성채널 여행브이로그", 282000, "2026-05-10", 234622, None, 169, "하드케이스 25"),
    ("Q3a", "youtube", "합성채널 동네친구", 1560000, "2026-07-14", 594925, 5600, 484, "하드케이스 28"),
    ("Q3b", "youtube", "합성채널 미키여행", 376000, "2026-07-28", 380854, 6300, 355, "하드케이스 28"),
    ("Q3c", "instagram", "합성 운동크루", 968000, "2026-08-04", 312398, 10200, 545, "하드케이스 28"),
    ("Q3d", "instagram", "합성 신혼여행", 200000, "2026-08-21", 323066, 3500, 160, "블랙라벨 24"),
    ("Q3e", "instagram", "합성 세가족", 413000, "2026-09-02", 8258996, 1600, 95, "하드케이스 25"),
]


def posts_csv() -> str:
    text = "post_id,brand,channel,creator,owner_type,posted_at,measured_at,followers,followers_measured_at,views,likes,comments,likes_hidden,product,url\n"
    for pid, ch, creator, fol, posted, views, likes, comments, product in POSTS:
        hidden = "true" if likes is None else "false"
        text += (f"{pid},B1,{ch},{creator},creator,{posted},2026-10-01,{fol},2026-10-01,{views if views else ''},"
                 f"{likes if likes is not None else ''},{comments},{hidden},{product},https://example.com/post/{pid}\n")
    return text


def make_image(path: Path, w: int, h: int, seed: int, headline: str, sub: str):
    """Thumbnail-like synthetic image with in-image text near the bottom edge (crop test)."""
    rnd = random.Random(seed)
    img = Image.new("RGB", (w, h))
    top = tuple(rnd.randint(40, 200) for _ in range(3))
    bot = tuple(rnd.randint(20, 120) for _ in range(3))
    px = img.load()
    for y in range(h):
        t = y / h
        c = tuple(int(top[i] * (1 - t) + bot[i] * t) for i in range(3))
        for x in range(w):
            px[x, y] = c
    d = ImageDraw.Draw(img)
    for _ in range(6):
        x0, y0 = rnd.randint(0, w), rnd.randint(0, h)
        r = rnd.randint(h // 10, h // 4)
        d.ellipse([x0 - r, y0 - r, x0 + r, y0 + r], fill=tuple(rnd.randint(60, 255) for _ in range(3)))
    img = img.filter(ImageFilter.GaussianBlur(3))
    d = ImageDraw.Draw(img)
    # Subject: a luggage-like rounded box in the center
    bw, bh = int(w * 0.28), int(h * 0.5)
    d.rounded_rectangle([w // 2 - bw // 2, h // 2 - bh // 2, w // 2 + bw // 2, h // 2 + bh // 2], radius=18, fill=(225, 225, 230),
                        outline=(80, 80, 90), width=4)
    big = ImageFont.truetype(str(FONTS_DIR / "NotoSansKR-Bold.otf"), max(18, h // 9))
    small = ImageFont.truetype(str(FONTS_DIR / "NotoSansKR-Bold.otf"), max(12, h // 16))
    tw = d.textlength(headline, font=big)
    d.rectangle([0, h - h // 5 - 6, w, h], fill=(10, 10, 10))
    d.text(((w - tw) / 2, h - h // 5), headline, font=big, fill=(255, 220, 0))
    d.text((12, 10), sub, font=small, fill=(255, 255, 255))
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "JPEG", quality=88)


CASES = [
    ("누리볼트", "라이브·팝업 연계", "센텀 팝업", "2026-02-03", 1920, 1080, ["라이브 커머스 첫 방송 이후 같은 비주얼로 팝업 운영 — 광고에서 체험·구매까지 이어지는 흐름"], "자사 캠페인 비주얼을 홈쇼핑·백화점 팝업에 동시 활용", [("views", 116799), ("percent", "0.97")]),
    ("코어딕스", "롱폼 실사용 리뷰", "실제 체험기", "2026-03-20", 1280, 720, ["가격 대비 기능 하나를 롱폼에서 반복 시연하고 설명란에 여행 혜택 멤버십을 묶어 패키지로 제시"], "캐리어와 여행 혜택을 묶은 번들 링크", [("views", 116799), ("percent", "0.97")]),
    ("코어딕스", "비교 리뷰", "비교 리뷰", "2026-03-27", 1080, 1080, ["마이크로 리뷰어가 고가 브랜드를 제목 기준점으로 걸고 가격 대비 스펙을 비교하는 프레임"], "내구 테스트·보증 수리 실적 기반 반박 콘텐츠", [("views", 16676), ("percent", "0.63")]),
    ("다온리모", "구독자 시크릿 링크", "명작 캐리어 추천", "2026-08-08", 1280, 720, ["수수료 수령을 고지하고 구독자 전용 링크로 할인 — 후속 비교 영상에서 비교 기준에 편입"], "패션 큐레이터 채널과 공식 비교·전용가 링크", [("views", 182072), ("comments", 313)]),
    ("한결나덕", "단독 기획전", "1등 캐리어", "2026-08-17", 1440, 1080, ["국내 한 달 사용 후 고가 캐리어와 비교하는 '명품 대비 가성비' 프레임 + 커머스 전용가"], "신규 수입 브랜드 진입 — 기준 브랜드 지위 방어", [("views", 29633), ("percent", "1.16")]),
    ("마루헨제이", "7일 한정 특가", "여행템 1위", "2026-07-20", 1280, 720, ["'후회되는 캐리어 1위' 롱폼 + 가격 인상 전 크리에이터 전용 최저가 한정 마켓"], "단독 외 크리에이터 공구 채널", [("views", 16774), ("percent", "1.55")]),
    ("로우온", "단독 기획전", "드디어 찾았다", "2026-07-23", 1920, 1080, ["백팩 브랜드가 휠 캐리어를 수납력 테스트 롱폼으로 소개하고 공식몰 단독 기획전으로 바로 연결"], "백팩 브랜드의 러기지 진입 — 교차 판매 역위협", [("views", 14530), ("percent", "0.95")]),
]


def quoted_parts(text: str) -> list[Part]:
    """'...' quotes become name parts (titles may contain digits); the rest is plain text."""
    parts = []
    for i, chunk in enumerate(text.split("'")):
        if chunk:
            parts.append(Part(type="name", text=f"'{chunk}'") if i % 2 else Part(type="text", text=chunk))
    return parts


def build_inputs(asset_dir: Path):
    project = load_project(project_json())
    facts = import_facts_csv(facts_csv(), project, "quality-facts")
    posts = import_posts_csv(posts_csv(), project, "quality-posts")
    assert not facts.errors and not posts.errors, (facts.errors, posts.errors)
    all_facts = accept_facts(facts.facts + posts.facts)
    all_posts = accept_posts(posts.posts)
    materials: list[CaseMaterial] = []
    for i, (entity, label, title, day, w, h, desc, impl, metrics) in enumerate(CASES):
        img_path = asset_dir / f"case{i + 1}.jpg"
        make_image(img_path, w, h, 100 + i, title, f"{entity} 합성 이미지")
        src = SourceRef(id=f"SRC-Q{i + 1:02d}", title=f"{entity} · {label}", url=f"https://example.com/synthetic/campaign/{i + 1}/" + "detail-page-" * (1 + i % 3),
                        publisher="합성 출처", published_at=date.fromisoformat(day), source_type="synthetic")
        ev = f"EV-Q{i + 1:02d}"
        fact_ids = []
        for metric, value in metrics:
            f = make_manual_fact(brand_id="B1", entity=entity, metric=metric, value=value, measured_at=date(2026, 9, 30),
                                 source=src.title, source_id=src.id, evidence_id=ev,
                                 label={"views": "조회", "percent": "반응률", "comments": "댓글"}[metric], status="eligible")
            all_facts.append(f)
            fact_ids.append(f.id)
        # Wide images as-is; squarer images cropped from the top so the bottom headline stays readable.
        crop = Crop(x=0.0, y=0.0, w=1.0, h=1.0) if w / h > 1.5 else Crop(x=0.0, y=0.22, w=1.0, h=0.78)
        asset = AssetRef(id=f"AS-Q{i + 1:02d}", source_id=src.id, path=str(img_path), width=w, height=h, crop=crop,
                         title=title, review_status="accepted")
        claims = [ClaimRef(id=f"CL-Q{i + 1:02d}a", kind="fact", parts=quoted_parts(desc[0]), evidence_ids=[ev],
                           review_status="accepted"),
                  ClaimRef(id=f"CL-Q{i + 1:02d}b", kind="interpretation", parts=quoted_parts(impl),
                           evidence_ids=[ev], review_status="accepted")]
        materials.append(CaseMaterial(id=ev, brand_id="B1", entity=entity, section_id="campaign", title=title,
                                      label=f"{entity} · {label}", source=src, activity_date=date.fromisoformat(day),
                                      asset=asset, metric_fact_ids=fact_ids, claims=claims, review_status="accepted",
                                      order=i))
    # p.40 reference image for the influencer image+table variant
    ref_path = asset_dir / "influencer_ref.jpg"
    make_image(ref_path, 1280, 720, 999, "당일치기 여행", "합성채널 동네친구 · 합성 이미지")
    ref_src = SourceRef(id="SRC-QREF", title="합성채널 동네친구 × 하드케이스 28", url="https://example.com/synthetic/video/Q3a",
                        publisher="합성 출처", published_at=date(2026, 7, 14), source_type="synthetic")
    materials.append(CaseMaterial(
        id="EV-QREF", brand_id="B1", entity="브랜드A", section_id="influencer", title="합성채널 동네친구 × 하드케이스 28",
        source=ref_src, activity_date=date(2026, 7, 14),
        asset=AssetRef(id="AS-QREF", source_id=ref_src.id, path=str(ref_path), width=1280, height=720,
                       title="합성채널 동네친구 × 하드케이스 28 (07.14)", description="합성 레퍼런스 이미지 · 성과는 오른쪽 표 참조",
                       review_status="accepted"),
        claims=[], review_status="accepted"))
    return project, all_facts, all_posts, materials


REFERENCE_PAGES = {26: "2-8a", 27: "2-8b", 29: "2-8d", 40: "3-1-B1", 54: "C1-p2", 68: "C1", 89: "5-recap", 104: "A-source"}
