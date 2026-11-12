"""Stage 2 with fake providers (no network): research runs, ledger/cache, budget, failures,
influencer collection and AI lead proposals (DEVELOPMENT_PLAN 단계 2 완료 조건; PRD A10, A14)."""
import io
import json
import re
from datetime import date

import pytest
from PIL import Image
from sqlalchemy import select

from app.db import SessionLocal
from app.models import FactRow, Material, PostRow, ProviderCache, ProviderCall, ResearchItem, Source, new_id, utcnow
from app.services import (
    aliases, case_commentary, commerce_collect, direction, hero_products, industry, industry_keywords, insights,
    material_ai, official_accounts, outline, research, synthesis,
)
from integrations.base import CallResult, ProviderError
from integrations.fetch.page import Page

ARTICLE = ("경쟁X는 2026년 3월 성수동에서 팝업스토어를 열었다. 행사 기간 방문객은 12000명으로 집계됐다. "
           "브랜드는 신제품 캐리어를 체험 공간에 배치하고 현장 구매 혜택을 제공했다.")


def png(color: tuple[int, int, int] = (20, 60, 120)) -> bytes:
    b = io.BytesIO()
    Image.new("RGB", (800, 450), color).save(b, "PNG")
    return b.getvalue()


class Fakes:
    def __init__(self):
        self.calls: dict[str, int] = {}
        self.fail_search = None
        self.fail_trends = False
        self.search_name = "경쟁X"  # how the fake articles name the brand
        self.naver_items: dict = {}  # P2-3 가짜 네이버 검색 결과(종류별), 비어 있으면 결과 없음
        self.naver_denied: set = set()  # 'API HUB에서 비활성'으로 막을 검색 종류

    def _hit(self, name):
        self.calls[name] = self.calls.get(name, 0) + 1

    def search(self, queries, **kw):
        self._hit("search")
        if self.fail_search:
            raise ProviderError(self.fail_search, "fake failure", 403)
        return CallResult(data={"id": "s1", "results": [
            {"title": f"{self.search_name} 성수 팝업", "url": "https://news.example.com/a1", "snippet": "팝업 소식", "date": "2026-03-05"},
            {"title": f"{self.search_name} 영상", "url": "https://www.youtube.com/watch?v=abc", "snippet": "영상", "date": None},
        ]}, cost_usd=0.005)

    def fetch_page(self, url, **kw):
        self._hit("fetch_page")
        return Page(url=url, final_url=url, title="경쟁X, 성수 팝업 열어", text=ARTICLE, content_hash="h1",
                    published="2026-03-05", publisher="예시뉴스", image_urls=["https://news.example.com/og.png"])

    def fetch_image(self, url, **kw):
        self._hit("fetch_image")
        # Distinct per URL — a real photo per post, not the same bytes (and sha256) every time.
        return png((abs(hash(url)) % 200, abs(hash(url[::-1])) % 200, 80))

    def structured(self, system, user, schema, **kw):
        props = schema["properties"]
        if set(props) == {"brands"}:
            item_props = set(schema["properties"]["brands"]["items"]["properties"])
            if item_props == {"name", "industry"}:  # 업종 추천: echo back whichever brand name was asked about
                self._hit("industry")
                names = user.split("<brands>\n")[-1].split("\n</brands>")[0].splitlines()
                return CallResult(data={"brands": [{"name": n, "industry": "패션"} for n in names]},
                                  usage={"model": "fake"}, cost_usd=0.001)
            self._hit("aliases")  # 다른 표기: only the competitor has a known English name
            return CallResult(data={"brands": [{"name": "경쟁X", "aliases": ["CompetitorX", "경쟁X"]}]},
                              usage={"model": "fake"}, cost_usd=0.001)
        if set(props) == {"profiles"}:  # 공식 계정 후보
            self._hit("official_accounts")
            return CallResult(data={"profiles": [
                {"channel": "instagram", "url": "https://instagram.com/competitorx_official", "confident": True}]},
                              usage={"model": "fake"}, cost_usd=0.001)
        if set(props) == {"products"}:  # 대표 상품 후보 (Phase 2)
            self._hit("hero_products")
            return CallResult(data={"products": [{"name": "에어맥스 95", "confident": True}]},
                              usage={"model": "fake"}, cost_usd=0.001)
        if set(props) == {"reviews"}:  # 커머스 리뷰 키워드 분류 (Phase 2) — 간단한 키워드 규칙으로 흉내
            self._hit("commerce_keywords")
            rows = []
            for m in re.finditer(r"^(\d+)\. (.+)$", user, re.M):
                idx, text = int(m.group(1)), m.group(2)
                if "쿠션감이 좋" in text:
                    rows.append({"index": idx, "sentiment": "positive", "keywords": ["쿠션감"], "blocks_purchase": False})
                elif "쿠션감이 부족" in text:
                    rows.append({"index": idx, "sentiment": "negative", "keywords": ["쿠션감"], "blocks_purchase": True})
                else:
                    rows.append({"index": idx, "sentiment": "neutral", "keywords": [], "blocks_purchase": False})
            return CallResult(data={"reviews": rows}, usage={"model": "fake"}, cost_usd=0.002)
        if set(props) == {"keywords"}:  # 업종별 키워드 힌트 후보 (피드백 #1)
            self._hit("industry_keywords")
            return CallResult(data={"keywords": [{"text": "트래블룩", "confident": True}]},
                              usage={"model": "fake"}, cost_usd=0.001)
        if set(props) == {"comments"}:  # 댓글 감성 분류 (피드백 #2) — 간단한 키워드 규칙으로 흉내
            self._hit("comment_sentiment")
            rows = []
            for m in re.finditer(r"^(\d+)\. (.+)$", user, re.M):
                idx, text = int(m.group(1)), m.group(2)
                if "예뻐요" in text or "재구매" in text:
                    rows.append({"index": idx, "sentiment": "positive", "pain_points": []})
                elif "별로" in text or "실망" in text:
                    rows.append({"index": idx, "sentiment": "negative", "pain_points": ["품질 불만"]})
                else:
                    rows.append({"index": idx, "sentiment": "neutral", "pain_points": []})
            return CallResult(data={"comments": rows}, usage={"model": "fake"}, cost_usd=0.001)
        if set(props) == {"docs"}:  # P2-5 블로그 문서 유형 — 표시 문구·간단한 키워드 규칙으로 흉내
            self._hit("blog_type_classify")
            rows = []
            for m in re.finditer(r'<doc index="(\d+)">(.*?)</doc>', user, re.S):
                idx, body = int(m.group(1)), m.group(2)
                kind = ("sponsored" if "<markers>sponsored" in body else
                        "shopping_affiliate" if "affiliate" in body.split("</markers>")[0] else
                        "promo_template" if "입고 안내" in body else "real_use" if "써 보니" in body else "other")
                rows.append({"index": idx, "type": kind})
            return CallResult(data={"docs": rows}, usage={"model": "fake"}, cost_usd=0.002)
        self._hit("structured")
        if "es_company" in props or "swot_lead" in props or "problem_lead" in props:  # 종합 장표(고른 유형만)
            pages = json.loads(re.search(r"<pages>\n(.*)\n</pages>", user, re.S).group(1))
            page_ids = {page["id"] for page in pages}
            first_ref = pages[0]["id"]
            competitor_ref = "2-8a" if "2-8a" in page_ids else first_ref
            first_fact = next((binding["fact_ref"] for page in pages if page["id"] == competitor_ref
                               for binding in page.get("bindings", [])), None)
            data: dict = {}
            if "es_company" in props:  # one line has a number and one points at a page that doesn't exist
                data.update({
                    "es_company": [{"text": "크리에이터 게시물 중심의 자사 관측", "ref": first_ref,
                                    "fact_ref": None}],
                    "es_competitor": [{"text": "경쟁 세트 안 검색 점유 우위 축소", "ref": competitor_ref,
                                       "fact_ref": first_fact},
                                      {"text": "점유 12퍼센트 하락", "ref": "2-8a"}, {"text": "없는 장 근거", "ref": "Z-9"}],
                    "es_customer": [], "task": "검색 점유 방어를 위한 접점 확대 필요",
                    "insights": [{"title": "검색 우위 축소", "body": "경쟁 세트 안에서 검색 점유가 줄어드는 흐름",
                                  "ref": competitor_ref, "fact_ref": first_fact}]})
            if "swot_lead" in props:
                line = lambda text: {"text": text, "ref": competitor_ref, "fact_ref": first_fact}
                data.update({"swot_lead": "자사 접점은 넓고 검색 점유는 낮은 편", "S": [line("크리에이터 협업 접점")],
                            "W": [line("검색 점유 우위 축소")], "O": [line("카테고리 조합어 검색 수요")],
                            "T": [line("경쟁사 검색 점유 상승")]})
            if "problem_lead" in props:
                line = lambda text: {"text": text, "ref": competitor_ref, "fact_ref": first_fact}
                data.update({"problem_lead": "검색 접점에서 경쟁 열위",
                            "problems": [line("검색 노출 열세"), line("콘텐츠 반응 둔화")],
                            "solutions": [{"title": "검색 접점 확대", "body": "크리에이터 콘텐츠에 브랜드명 검색 유도 문구 배치",
                                           "ref": competitor_ref, "fact_ref": first_fact}]})
            return CallResult(data=data, usage={"model": "fake"}, cost_usd=0.01)
        if "action" in props:  # 초안 흐름 장표 피드백
            fb = user.split("<feedback>")[-1]
            if "빼" in fb:
                return CallResult(data={"reply": "이 장을 뺐습니다.", "action": "omit", "claim": [], "evidence": []},
                                  usage={"model": "fake"}, cost_usd=0.002)
            if "순서" in fb:
                return CallResult(data={"reply": "장 순서는 이 단계에서 바꿀 수 없습니다.", "action": "none", "claim": [],
                                        "evidence": []}, usage={"model": "fake"}, cost_usd=0.002)
            seg = [{"text": "브랜드 검색 점유 12% 우위 축소", "fact_ref": None, "accent": True}] if "깨기" in fb else \
                  [{"text": "브랜드 검색 점유 ", "fact_ref": None, "accent": False},
                   {"text": "우위가 줄어든 흐름", "fact_ref": None, "accent": True}]
            ev = [[{"text": "자사 점유 ", "fact_ref": None, "accent": False}, {"text": "", "fact_ref": 1, "accent": False}]]
            return CallResult(data={"reply": "리드를 다시 썼습니다.", "action": "rewrite_lead", "claim": seg, "evidence": ev},
                              usage={"model": "fake"}, cost_usd=0.002)
        if "suggestions" in props:  # 문장 추천: one verbatim quote, one made-up quote, one with a bare number
            return CallResult(data={"suggestions": [
                {"kind": "fact", "text": "성수동 팝업에 신제품 체험 공간 배치", "quote": "브랜드는 신제품 캐리어를 체험 공간에 배치하고 현장 구매 혜택을 제공했다."},
                {"kind": "interpretation", "text": "원문에 없는 관찰", "quote": "원문에 없는 문장."},
                {"kind": "fact", "text": "방문객 12000명 집계", "quote": "행사 기간 방문객은 12000명으로 집계됐다."}]},
                usage={"model": "fake"}, cost_usd=0.002)
        if set(props) == {"text"}:  # 다듬기: keeps the fact token unless asked to break it
            keep = re.search(r"\{\{[^}]+\}\}", user)
            return CallResult(data={"text": ("조회 " + keep.group(0) + " 규모의 체험형 확산 확인") if keep and "깨기" not in user
                                    else "체험형 팝업으로 화제성 확보 99"}, usage={"model": "fake"}, cost_usd=0.001)
        if set(props) == {"summary"}:
            return CallResult(data={"summary": "직접 만든 카드의 요약입니다."}, usage={"model": "fake"}, cost_usd=0.001)
        if "search_query" in props:  # 자료 대화: asks for a search first, answers from it after
            if "<search>" not in user:
                return CallResult(data={"answer": "원문에서 확인되지 않습니다", "search_query": "경쟁X 팝업 방문객", "used": []},
                                  usage={"model": "fake"}, cost_usd=0.002)
            return CallResult(data={"answer": "추가 기사에 따르면 주말 방문이 많았습니다.", "search_query": None, "used": [1, 9]},
                              usage={"model": "fake"}, cost_usd=0.002)
        if "keywords" in props:  # 조사 방향 대화
            return CallResult(data={
                "reply": "기간을 최근 12개월로 바꾸고 팝업 사례를 먼저 보게 했습니다.", "enabled": True, "period": "months",
                "months": 12, "start": None, "end": None, "channels": ["web", "instagram", "없는채널"],
                "targets": ["경쟁X"], "max_items": 4, "focus": "팝업·오프라인 행사 사례를 먼저 봅니다.",
                "keywords": ["팝업스토어"]}, usage={"input_tokens": 300, "output_tokens": 80, "model": "fake"}, cost_usd=0.002)
        if "detail" in schema["properties"]:  # P4 case commentary
            if "이전 답의 문제" not in user:
                return CallResult(data={"detail": "3일 만에 완판된 협업 캡슐 컬렉션", "implication": "자사도 한정판 캡슐로 화제성 확보"},
                                  usage={"input_tokens": 100, "output_tokens": 30, "model": "fake"}, cost_usd=0.001)
            return CallResult(data={"detail": "짧은 기간에 완판된 협업 캡슐 컬렉션", "implication": "자사도 한정판 캡슐로 화제성 확보"},
                              usage={"input_tokens": 100, "output_tokens": 30, "model": "fake"}, cost_usd=0.001)
        if "facts" in schema["properties"]:  # extraction
            # Phase 3-3: when the prompt names other self brands, claim the content is really about
            # the first of them — otherwise stay inert (existing single-brand tests are unaffected).
            other_brands = re.search(r"다른 자사 브랜드: (.+)", user)
            primary_brand = other_brands.group(1).split(", ")[0] if other_brands else None
            return CallResult(data={
                "relevant": True, "relevance_note": "", "activity_date": "2026-03-01",
                "summary": "성수동 팝업에서 신제품 체험 공간을 열어 방문객을 모은 활동입니다.",
                # Phase 3-2/피드백 #1: section_id가 "market"일 때만 적용 — 3-4(규제와 정책) 질문이면 policy로.
                "market_aspect": "policy" if "정책" in user else "channel",
                "primary_brand": primary_brand, "related_brands": [],
                "facts": [{"label": "방문객", "metric": "count", "value": "12000", "quote": "행사 기간 방문객은 12000명으로 집계됐다.",
                          "substituted": True},  # Phase 3-2: only applied when section_id is "market_kpi"
                          {"label": "가짜", "metric": "count", "value": "999", "quote": "원문에 없는 문장."}],
                "claims": [{"kind": "fact", "text": "성수동 팝업에 신제품 체험 공간 배치", "quote": "브랜드는 신제품 캐리어를 체험 공간에 배치하고 현장 구매 혜택을 제공했다."},
                           {"kind": "interpretation", "text": "방문객 {{1}} 규모의 체험형 접점", "quote": "행사 기간 방문객은 12000명으로 집계됐다."},
                           {"kind": "fact", "text": "3월 팝업 개최", "quote": "경쟁X는 2026년 3월 성수동에서 팝업스토어를 열었다."}],
            }, usage={"input_tokens": 1000, "output_tokens": 200, "model": "fake"}, cost_usd=0.008, cost_is_estimate=False)
        if set(props) == {"insights"}:  # P3-5: all three cards cite a displayed fact
            card = lambda title, body: {"title": [{"text": title, "fact_ref": None, "accent": False}],
                                        "body_segments": [{"text": body, "fact_ref": None, "accent": False},
                                                          {"text": "", "fact_ref": 1, "accent": False}]}
            return CallResult(data={"insights": [card("수치 확인", "본문 수치 "), card("격차 점검", "비교 수치 "),
                                                   card("운영 우선", "다음 확인 값 ")]},
                              usage={"model": "fake"}, cost_usd=0.003, cost_is_estimate=False)
        # headline (P3-4): first answer breaks the digit rule and has no evidence line, the rewrite is valid
        n = self.calls["structured"]
        if "이전 답의 문제" not in user:
            data = {"claim": [{"text": "검색 점유 12M 기준 우위 축소", "fact_ref": None, "accent": False}], "evidence": []}
        else:
            data = {"claim": [{"text": "브랜드 검색 점유 ", "fact_ref": None, "accent": False},
                              {"text": "우위 축소", "fact_ref": None, "accent": True}],
                    "evidence": [[{"text": "격차 ", "fact_ref": None, "accent": False}, {"text": "", "fact_ref": 1, "accent": False}],
                                 [{"text": "'검색 우위'가 줄어드는 흐름", "fact_ref": None, "accent": False}]]}
        return CallResult(data=data, usage={"input_tokens": 500, "output_tokens": 50, "model": "fake"},
                          cost_usd=0.003 + n * 0, cost_is_estimate=False)

    def instagram_post(self, url, **kw):
        self._hit("instagram_post")
        return CallResult(data={"platform": "instagram", "url": url, "post_id": "C1x", "posted_at": "2026-05-02", "title": "",
                                "creator": "ig_creator", "followers": None, "views": None, "likes": None, "comments": 120,
                                "likes_hidden": True, "image_urls": [], "paid_promotion": None}, cost_usd=0.002)

    def instagram_profile(self, handle, **kw):
        self._hit("instagram_profile")
        return CallResult(data={"followers": 80000, "name": handle, "bio": "서울 사는 러너"}, cost_usd=0.002)

    def youtube_video(self, url, **kw):
        self._hit("youtube_video")
        return CallResult(data={"platform": "youtube", "url": url, "post_id": "vid1", "posted_at": "2026-06-10", "title": "리뷰",
                                "creator": "유튜버", "channel_url": "https://www.youtube.com/@yt", "followers": None,
                                "views": 300000, "likes": 6000, "comments": 400, "likes_hidden": False,
                                "image_urls": [], "paid_promotion": True}, cost_usd=0.002)

    def youtube_channel(self, url=None, **kw):
        self._hit("youtube_channel")
        return CallResult(data={"subscribers": 200000, "name": "유튜버"}, cost_usd=0.002)

    def instagram_user_posts(self, handle, next_max_id=None, **kw):
        self._hit("instagram_user_posts")
        if next_max_id:
            return CallResult(data={"posts": [], "next_max_id": None, "more_available": False}, cost_usd=0.002)
        posts = [
            {"post_id": "p1", "posted_at": "2026-08-05", "likes": 500, "comments": 10, "views": None,
             "url": "https://instagram.com/p/p1/", "image_url": "https://img.example.com/p1.jpg"},
            # p2는 동영상 게시물이라 재생수가 있다(사진 게시물은 플랫폼이 공개하지 않아 None).
            {"post_id": "p2", "posted_at": "2026-09-10", "likes": 900, "comments": 20, "views": 45000,
             "url": "https://instagram.com/p/p2/", "image_url": "https://img.example.com/p2.jpg"},
            {"post_id": "p3", "posted_at": "2026-09-20", "likes": 100, "comments": 5, "views": None,
             "url": "https://instagram.com/p/p3/", "image_url": None},
        ]
        return CallResult(data={"posts": posts, "next_max_id": None, "more_available": False}, cost_usd=0.002)

    @staticmethod
    def _post_comments_result():
        comments = [
            {"id": "c1", "text": "진짜 예뻐요 재구매각", "posted_at": "2026-08-10", "likes": 2},
            {"id": "c2", "text": "별로예요 실망", "posted_at": "2026-08-11", "likes": 0},
            {"id": "c3", "text": "ㅎㅇ", "posted_at": "2026-08-12", "likes": 0},
        ]
        return CallResult(data={"comments": comments, "cursor": None}, cost_usd=0.002)

    def instagram_post_comments(self, url, cursor=None, **kw):
        self._hit("instagram_post_comments")
        return self._post_comments_result()

    def youtube_video_comments(self, url, cursor=None, **kw):
        self._hit("youtube_video_comments")
        return self._post_comments_result()

    def tiktok_video_comments(self, url, cursor=None, **kw):
        self._hit("tiktok_video_comments")
        return self._post_comments_result()

    def facebook_post_comments(self, url, cursor=None, **kw):
        self._hit("facebook_post_comments")
        return self._post_comments_result()

    # 피드백 #5(SNS 네이티브 검색): 기존 VOC 테스트를 건드리지 않도록 기본은 빈 결과 — 전용 테스트가
    # research.PROVIDERS["twitter_search_posts"]/["threads_search"]를 따로 덮어쓴다.
    def twitter_search_posts(self, query, cursor=None, **kw):
        self._hit("twitter_search_posts")
        return CallResult(data={"posts": [], "cursor": None}, cost_usd=0.002)

    def threads_search(self, query, **kw):
        self._hit("threads_search")
        return CallResult(data={"posts": []}, cost_usd=0.002)

    # P2-8: 틱톡·유튜브 검색도 기본은 빈 결과 — 전용 테스트가 덮어쓴다.
    def tiktok_search_keyword(self, query, region=None, cursor=None, **kw):
        self._hit("tiktok_search_keyword")
        return CallResult(data={"posts": [], "cursor": None, "has_more": False}, cost_usd=0.002)

    def youtube_search(self, query, **kw):
        self._hit("youtube_search")
        return CallResult(data={"videos": []}, cost_usd=0.002)

    # P2-9 광고 라이브러리: 기본은 아무것도 찾지 못함 — 전용 테스트가 덮어쓴다.
    def facebook_ad_companies(self, query, **kw):
        self._hit("facebook_ad_companies")
        return CallResult(data={"pages": []}, cost_usd=0.002)

    def facebook_ad_search(self, query, country=None, cursor=None, **kw):
        self._hit("facebook_ad_search")
        return CallResult(data={"ads": [], "cursor": None, "total": 0}, cost_usd=0.002)

    def facebook_company_ads(self, page_id, country=None, cursor=None, **kw):
        self._hit("facebook_company_ads")
        return CallResult(data={"ads": [], "cursor": None, "total": 0}, cost_usd=0.002)

    def tiktok_ad_library_search(self, query, cursor=None, **kw):
        self._hit("tiktok_ad_library_search")
        return CallResult(data={"ads": [], "cursor": None, "has_more": False}, cost_usd=0.002)

    def google_ad_advertisers(self, query, **kw):
        self._hit("google_ad_advertisers")
        return CallResult(data={"advertisers": []}, cost_usd=0.002)

    def google_company_ads(self, advertiser_id, region=None, cursor=None, **kw):
        self._hit("google_company_ads")
        return CallResult(data={"ads": [], "cursor": None, "total": 0}, cost_usd=0.002)

    def youtube_channel_videos(self, channel_id=None, handle=None, continuation_token=None, **kw):
        self._hit("youtube_channel_videos")
        videos = [{"id": "v1", "url": "https://youtube.com/watch?v=v1", "title": "영상1", "views": 1000,
                  "published_at": "2026-09-01", "length_seconds": 120, "is_short": False}]
        return CallResult(data={"videos": videos, "continuation_token": None}, cost_usd=0.002)

    def youtube_channel_shorts(self, channel_id=None, handle=None, continuation_token=None, **kw):
        self._hit("youtube_channel_shorts")
        return CallResult(data={"shorts": [], "continuation_token": None}, cost_usd=0.002)

    # P2-6 공식 계정 채널: 기본은 계정이 없거나 글이 없는 것처럼 — 전용 테스트가 덮어쓴다.
    def tiktok_profile(self, handle, **kw):
        self._hit("tiktok_profile")
        raise ProviderError("SOURCE_UNAVAILABLE", "TikTok 계정을 찾을 수 없습니다", 404)

    def tiktok_profile_videos(self, handle, max_cursor=None, **kw):
        self._hit("tiktok_profile_videos")
        return CallResult(data={"posts": [], "cursor": None, "has_more": False}, cost_usd=0.002)

    def facebook_profile(self, url, **kw):
        self._hit("facebook_profile")
        raise ProviderError("SOURCE_UNAVAILABLE", "Facebook 페이지를 찾을 수 없습니다", 404)

    def facebook_profile_posts(self, url, cursor=None, **kw):
        self._hit("facebook_profile_posts")
        return CallResult(data={"posts": [], "cursor": None}, cost_usd=0.002)

    def twitter_profile(self, handle, **kw):
        self._hit("twitter_profile")
        raise ProviderError("SOURCE_UNAVAILABLE", "X 계정을 찾을 수 없습니다", 404)

    def twitter_user_tweets(self, handle, **kw):
        self._hit("twitter_user_tweets")
        return CallResult(data={"posts": []}, cost_usd=0.002)

    def threads_profile(self, handle, **kw):
        self._hit("threads_profile")
        raise ProviderError("SOURCE_UNAVAILABLE", "Threads 계정을 찾을 수 없습니다", 404)

    def threads_user_posts(self, handle, **kw):
        self._hit("threads_user_posts")
        return CallResult(data={"posts": []}, cost_usd=0.002)

    def search_trend(self, groups, start, end, **kw):
        self._hit("search_trend")
        # One ratio per month in [start, end], distinct per group so shares aren't tied.
        months = []
        y, m = start.year, start.month
        while (y, m) <= (end.year, end.month):
            months.append(f"{y:04d}-{m:02d}-01")
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        base = {name: 20 + 10 * i for i, (name, _) in enumerate(groups)}
        return CallResult(data={"results": [
            {"group": name, "points": [{"period": period, "ratio": float(base[name] + i)} for i, period in enumerate(months)]}
            for name, _ in groups
        ]}, usage={"requests": 1}, cost_usd=0.0, cost_is_estimate=False)

    # P2-3 네이버 검색: 기본은 결과 없음(기존 테스트는 Perplexity 경로 그대로). 테스트가 naver_items를 채우면 그것을,
    # naver_denied에 넣은 종류는 'API HUB에서 비활성'으로 돌려준다.
    def naver_search(self, kind, query, *, display=100, start=1, sort="date", **kw):
        self._hit("naver_search")
        if kind in self.naver_denied:
            raise ProviderError("PROVIDER_AUTH", f"NAVER API HUB 앱에서 '{kind}' 검색 API가 활성화되어 있지 않습니다", 401)
        items = self.naver_items.get(kind, []) if start == 1 else []
        return CallResult(data={"total": len(items), "items": items, "via": "api_hub"}, usage={"requests": 1},
                          cost_usd=0.0, cost_is_estimate=False)

    SHOP_CODE = "50000001"  # 가짜 데이터: 모든 제품군이 패션잡화에만 클릭이 있다

    def shopping_keyword_trend(self, category, keywords, start, end, **kw):
        self._hit("shopping_keyword_trend")
        months = []
        y, m = start.year, start.month
        while (y, m) <= (end.year, end.month):
            months.append(f"{y:04d}-{m:02d}-01")
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        on = category == self.SHOP_CODE
        # 7·8월이 성수기(평균의 1.2배 이상)가 되도록
        return CallResult(data={"results": [
            {"group": name, "points": [{"period": p, "ratio": 100.0 if p[5:7] in ("07", "08") else 40.0 + j}
                                       for j, p in enumerate(months)] if on else []}
            for j, (name, _) in enumerate(keywords)
        ]}, usage={"requests": 1}, cost_usd=0.0, cost_is_estimate=False)

    def shopping_keyword_breakdown(self, category, keyword, by, start, end, **kw):
        self._hit("shopping_keyword_breakdown")
        groups = {"age": {"20": 30.0, "30": 50.0, "40": 20.0}, "gender": {"f": 60.0, "m": 40.0}}[by]
        return CallResult(data={"results": [{"group": category, "points": [
            {"period": "2026-01-01", "ratio": v, "group": g} for g, v in groups.items()]}]},
            usage={"requests": 1}, cost_usd=0.0, cost_is_estimate=False)

    def google_trends_search(self, keywords, geo="KR", **kw):
        self._hit("google_trends_search")
        if self.fail_trends:
            raise ProviderError("RATE_LIMITED", "Google Trends 접근 실패 (429)", 429)
        import time as _time
        points = [{"time": int(_time.mktime((2026, 7, d, 0, 0, 0, 0, 0, 0))), "values": {k: 40.0 + i for k in keywords}}
                  for i, d in enumerate((1, 8, 15, 22))]
        return CallResult(data={"points": points, "related_queries": [f"{keywords[0]} 신상", f"{keywords[0]} 세일"],
                                "geo": geo, "timeframe": "today 12-m"}, usage={"requests": 2}, cost_usd=0.0,
                          cost_is_estimate=False)


@pytest.fixture
def fakes(monkeypatch):
    f = Fakes()
    research.PROVIDERS.clear()
    research.PROVIDERS.update(search=f.search, fetch_page=f.fetch_page, fetch_image=f.fetch_image, structured=f.structured,
                              instagram_post=f.instagram_post, instagram_profile=f.instagram_profile, youtube_video=f.youtube_video,
                              youtube_channel=f.youtube_channel, naver_search_trend=f.search_trend,
                              instagram_user_posts=f.instagram_user_posts, youtube_channel_videos=f.youtube_channel_videos,
                              google_trends_search=f.google_trends_search, instagram_post_comments=f.instagram_post_comments,
                              youtube_video_comments=f.youtube_video_comments, tiktok_video_comments=f.tiktok_video_comments,
                              facebook_post_comments=f.facebook_post_comments,
                              twitter_search_posts=f.twitter_search_posts, threads_search=f.threads_search,
                              shopping_keyword_trend=f.shopping_keyword_trend,
                              shopping_keyword_breakdown=f.shopping_keyword_breakdown, naver_search=f.naver_search,
                              youtube_channel_shorts=f.youtube_channel_shorts, tiktok_profile=f.tiktok_profile,
                              tiktok_profile_videos=f.tiktok_profile_videos, facebook_profile=f.facebook_profile,
                              facebook_profile_posts=f.facebook_profile_posts, twitter_profile=f.twitter_profile,
                              twitter_user_tweets=f.twitter_user_tweets, threads_profile=f.threads_profile,
                              threads_user_posts=f.threads_user_posts, tiktok_search_keyword=f.tiktok_search_keyword,
                              youtube_search=f.youtube_search, facebook_ad_companies=f.facebook_ad_companies,
                              facebook_company_ads=f.facebook_company_ads, facebook_ad_search=f.facebook_ad_search,
                              tiktok_ad_library_search=f.tiktok_ad_library_search,
                              google_ad_advertisers=f.google_ad_advertisers, google_company_ads=f.google_company_ads)
    aliases.STRUCTURED.clear()
    aliases.STRUCTURED.append(f.structured)
    industry.STRUCTURED.clear()
    industry.STRUCTURED.append(f.structured)
    official_accounts.STRUCTURED.clear()
    official_accounts.STRUCTURED.append(f.structured)
    official_accounts.SEARCH.clear()
    official_accounts.SEARCH.append(lambda qs, **kw: f.search(qs, **kw))
    hero_products.STRUCTURED.clear()
    hero_products.STRUCTURED.append(f.structured)
    hero_products.SEARCH.clear()
    hero_products.SEARCH.append(lambda qs, **kw: f.search(qs, **kw))
    commerce_collect.STRUCTURED.clear()
    commerce_collect.STRUCTURED.append(f.structured)
    industry_keywords.STRUCTURED.clear()
    industry_keywords.STRUCTURED.append(f.structured)
    industry_keywords.SEARCH.clear()
    industry_keywords.SEARCH.append(lambda qs, **kw: f.search(qs, **kw))
    insights.STRUCTURED.clear()
    insights.STRUCTURED.append(f.structured)
    case_commentary.STRUCTURED.clear()
    case_commentary.STRUCTURED.append(f.structured)
    direction.STRUCTURED.clear()
    direction.STRUCTURED.append(f.structured)
    material_ai.STRUCTURED.clear()
    material_ai.STRUCTURED.append(f.structured)
    material_ai.SEARCH.clear()
    material_ai.SEARCH.append(lambda qs, **kw: f.search(qs, **kw))
    outline.STRUCTURED.clear()
    outline.STRUCTURED.append(f.structured)
    synthesis.STRUCTURED.clear()
    synthesis.STRUCTURED.append(f.structured)
    for k in ("PERPLEXITY_API_KEY", "ANTHROPIC_API_KEY", "SCRAPECREATORS_API_KEY", "NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET"):
        monkeypatch.setenv(k, "test-key")
    monkeypatch.setenv("ANTHROPIC_MODEL", "fake-model")
    monkeypatch.setenv("RUN_BUDGET_USD", "5")
    yield f
    research.PROVIDERS.clear()
    aliases.STRUCTURED.clear()
    industry.STRUCTURED.clear()
    official_accounts.STRUCTURED.clear()
    official_accounts.SEARCH.clear()
    hero_products.STRUCTURED.clear()
    hero_products.SEARCH.clear()
    commerce_collect.STRUCTURED.clear()
    industry_keywords.STRUCTURED.clear()
    industry_keywords.SEARCH.clear()
    insights.STRUCTURED.clear()
    case_commentary.STRUCTURED.clear()
    direction.STRUCTURED.clear()
    material_ai.STRUCTURED.clear()
    material_ai.SEARCH.clear()
    outline.STRUCTURED.clear()
    synthesis.STRUCTURED.clear()


def ok(r, status=200):
    assert r.status_code == status, r.text
    return r.json()


def setup_project(client):
    p = ok(client.post("/v1/projects/sample"), 201)
    plan = ok(client.get(f"/v1/projects/{p['id']}/research-plan"))
    return p["id"], plan


def item(plan, section, entity=None):
    return next(i for i in plan["items"] if i["section_id"] == section and (entity is None or i["entity"] == entity))


def mute_other_commerce_platforms(monkeypatch, *, keep: str = "musinsa"):
    """커머스 리뷰 테스트가 무신사 하나만 다루고 싶을 때, 나머지 플랫폼은 '찾지 못함'으로 고정해
    실제 네트워크를 타지 않게 한다(app/services/commerce_collect.py가 플랫폼 전부를 돈다)."""
    from app.services.commerce_collect import PLATFORM_MODULES

    for platform, module in PLATFORM_MODULES.items():
        if platform != keep:
            monkeypatch.setattr(module, "find_product", lambda name, **kw: None)


def clear_cache():
    with SessionLocal() as db:
        db.query(ProviderCache).delete()
        db.commit()


def ledger_rows(pid):
    with SessionLocal() as db:
        return list(db.scalars(select(ProviderCall).where(ProviderCall.project_id == pid)))


def test_campaign_run_creates_candidates_without_rebilling(client, fakes):
    pid, plan = setup_project(client)
    it = item(plan, "campaign", "경쟁X")
    job = ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [it["id"]]}), 202)["job"]
    job = ok(client.get(f"/v1/jobs/{job['id']}"))
    assert job["state"] == "succeeded", job
    res = job["result"]["items"][it["id"]]
    assert res["status"] == "succeeded" and res["created"] == 2 and res["pages"] == 1 and res["images"] == 1
    assert res["facts"] == 1 and res["claims"] == 2  # fake quote and bare-digit claim are dropped
    assert any("원문 인용 불일치" in d for d in res["dropped"]) and any("근거 없는 숫자" in d for d in res["dropped"])

    mats = ok(client.get(f"/v1/projects/{pid}/materials"))
    article = next(m for m in mats if m["source"]["url"] == "https://news.example.com/a1")
    assert article["input_path"] == "auto" and article["review_status"] == "candidate"  # a person reviews every card
    assert article["scope_id"] == "3-7" and article["role"] == "competitor"  # its place in the 3C plan
    assert article["summary"].startswith("성수동 팝업")  # 해석 요약 comes with the extraction, no extra call
    with SessionLocal() as db:
        assert "방문객" in (db.get(Source, article["source"]["id"]).text or "")  # page text kept for later AI help
    assert article["source"]["publisher"] == "예시뉴스" and article["source"]["published_at"] == "2026-03-05"
    assert article["assets"][0]["review_status"] == "candidate" and article["assets"][0]["usage_basis"] == "source_reference"
    ai = [c for c in article["claims"] if c["author"] == "ai"]
    assert all(c["review_status"] == "pending" and c["quote"] for c in ai)
    interp = next(c for c in ai if c["kind"] == "interpretation")
    assert "12,000" in interp["text"] and interp["fact_ids"]  # number bound to an extracted fact
    assert article["facts"][0]["verification_status"] == "candidate" and article["facts"][0]["origin"] == "auto"
    social = next(m for m in mats if "youtube" in (m["source"]["url"] or ""))
    assert social["source"]["source_type"] == "social" and social["assets"] == []

    paid = [r for r in ledger_rows(pid) if r.status == "settled"]
    assert {r.provider for r in paid} == {"perplexity", "anthropic"}
    assert ok(client.get(f"/v1/projects/{pid}/usage"))["total_cost_usd"] > 0

    # Re-run without force: the succeeded item is skipped, no provider is called.
    before = dict(fakes.calls)
    job2 = ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [it["id"]]}), 202)["job"]
    assert ok(client.get(f"/v1/jobs/{job2['id']}"))["result"]["items"][it["id"]]["status"] == "skipped"
    assert fakes.calls == before
    # Forced re-run hits the response cache: no new paid search, existing URLs are not duplicated.
    job3 = ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [it["id"]], "force": True}), 202)["job"]
    r3 = ok(client.get(f"/v1/jobs/{job3['id']}"))["result"]["items"][it["id"]]
    assert fakes.calls["search"] == before["search"]
    assert r3["skipped_existing"] == 2 and len(ok(client.get(f"/v1/projects/{pid}/materials"))) == len(mats)
    assert any(r.status == "cache_hit" and r.job_id == job3["id"] for r in ledger_rows(pid))


def test_market_item_classifies_aspect_and_does_not_leak_to_other_sections(client, fakes):
    """Phase 3-2: 산업 카테고리 분석 원문은 market_aspect로 분류되고, 다른 조사 항목에는 영향이 없다."""
    pid, plan = setup_project(client)
    market_it = item(plan, "market")
    job = ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [market_it["id"]]}), 202)["job"]
    assert ok(client.get(f"/v1/jobs/{job['id']}"))["state"] == "succeeded"
    # Social cards (e.g. the fake's YouTube result) skip AI extraction entirely — only web pages are classified.
    market_mats = [m for m in ok(client.get(f"/v1/projects/{pid}/materials", params={"section_id": "market"}))
                  if m["source"]["source_type"] != "social"]
    assert market_mats and all(m["market_aspect"] == "channel" for m in market_mats)

    # A separate project avoids colliding with the fake's fixed URLs from the market run above.
    pid2, plan2 = setup_project(client)
    campaign_it = item(plan2, "campaign", "경쟁X")
    job2 = ok(client.post(f"/v1/projects/{pid2}/research-runs", json={"item_ids": [campaign_it["id"]]}), 202)["job"]
    assert ok(client.get(f"/v1/jobs/{job2['id']}"))["state"] == "succeeded"
    campaign_mats = [m for m in ok(client.get(f"/v1/projects/{pid2}/materials", params={"section_id": "campaign"}))
                     if m["source"]["source_type"] != "social"]
    assert campaign_mats and all(m["market_aspect"] is None for m in campaign_mats)  # market_aspect는 market 전용


def test_regulation_and_policy_item_shares_the_market_slide_as_a_policy_aspect(client, fakes):
    """피드백 #1 축 4(3-4 규제와 정책): 3-1과 같은 M1 장표로 합쳐지고, policy로 분류된다."""
    pid, plan = setup_project(client)
    policy_it = next(i for i in plan["items"] if i["scope_id"] == "3-4")
    assert policy_it["section_id"] == "market" and policy_it["role"] == "market"
    job = ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [policy_it["id"]]}), 202)["job"]
    assert ok(client.get(f"/v1/jobs/{job['id']}"))["state"] == "succeeded"
    mats = [m for m in ok(client.get(f"/v1/projects/{pid}/materials", params={"section_id": "market"}))
           if m["source"]["source_type"] != "social"]
    assert mats and all(m["market_aspect"] == "policy" for m in mats)
    assert all(m["scope_id"] == "3-4" for m in mats)

    # M1 isn't in the sample project's curated demo slide list — turn it on explicitly.
    project = ok(client.get(f"/v1/projects/{pid}"))
    ok(client.patch(f"/v1/projects/{pid}", json={"base_version": project["version"],
                                                "changes": {"enabled_slides": project["config"]["enabled_slides"] + ["M1"]}}))
    sp = ok(client.get(f"/v1/projects/{pid}/slide-plan"))
    m1 = next(s for s in sp["plan"] if s["slot_id"] == "M1")
    assert m1["readiness"] == "needs_input"  # 아직 아무것도 채택하지 않음
    assert m1["cause"] == "adopt"  # 모은 자료가 채택을 기다리는 중(3-1·3-4 둘 다 이 장표로 합쳐짐)


def test_market_kpi_item_only_appears_for_metric_industries_and_marks_substituted(client, fakes):
    """Phase 3-2: 업종 KPI는 지표 중심 업종에서만 켜지고, 대체 지표는 표시된다."""
    pid, plan = setup_project(client)
    assert not any(i["section_id"] == "market_kpi" for i in plan["items"])  # 업종 미설정 — 기본 꺼짐

    p = ok(client.get(f"/v1/projects/{pid}"))
    brand = p["config"]["brands"][0]
    ok(client.patch(f"/v1/projects/{pid}", json={"base_version": p["version"],
                                                 "changes": {"brands": [{**brand, "industry": "금융"}]}}))
    plan2 = ok(client.get(f"/v1/projects/{pid}/research-plan"))
    kpi_it = item(plan2, "market_kpi", "경쟁X")  # the fake's canned article titles only name "경쟁X"
    job = ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [kpi_it["id"]]}), 202)["job"]
    assert ok(client.get(f"/v1/jobs/{job['id']}"))["state"] == "succeeded"

    mats = [m for m in ok(client.get(f"/v1/projects/{pid}/materials", params={"section_id": "market_kpi"}))
           if m["source"]["source_type"] != "social"]
    assert mats
    facts = [f for m in mats for f in m["facts"]]
    assert facts and all(f["dims"].get("substituted") == "true" for f in facts)


def test_campaign_case_reassigns_to_the_brand_it_is_really_about(client, fakes):
    """Phase 3-3 사례 귀속 정리: 자사 브랜드가 여럿이면, 실은 다른 브랜드 활동인 원문은 그 브랜드로
    옮겨 붙고(귀속 판정), 그 브랜드의 장표 구간에만 들어간다(장표 분배)."""
    p = ok(client.post("/v1/projects", json={
        "name": "귀속 테스트", "client": "고객", "period": {"start": "2026-01-01", "end": "2026-09-30"},
        "brands": [{"id": "B1", "name": "브랜드A", "competitors": ["경쟁X"]},
                  {"id": "B2", "name": "브랜드B", "competitors": ["경쟁Y"]}]}), 201)
    pid = p["id"]
    fakes.search_name = "브랜드B"  # the fake's canned article titles must name the entity being researched
    plan = ok(client.get(f"/v1/projects/{pid}/research-plan"))
    b_campaign = item(plan, "campaign", "브랜드B")
    assert b_campaign["role"] == "self"
    job = ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [b_campaign["id"]]}), 202)["job"]
    assert ok(client.get(f"/v1/jobs/{job['id']}"))["state"] == "succeeded"

    mats = ok(client.get(f"/v1/projects/{pid}/materials", params={"section_id": "campaign"}))
    article = next(m for m in mats if m["source"]["url"] == "https://news.example.com/a1")
    assert article["brand_id"] == "B1" and article["entity"] == "브랜드A"  # B가 수집했지만 실은 A의 활동

    # B의 소셜 게시물("브랜드B 영상")은 추출을 거치지 않아 원래 그대로 B에 남는다 — 그건 의도된 동작.
    # 재귀속 대상인 기사("성수 팝업")는 A쪽 구간에만 나타나고 B쪽에는 나타나지 않아야 한다.
    slots = {s["slot_id"]: s for s in ok(client.get(f"/v1/projects/{pid}/slide-plan"))["plan"] if s["slot_id"].startswith("C1-")}
    assert slots["C1-B1"]["brand_id"] == "B1" and "성수 팝업" in slots["C1-B1"]["reason"]
    assert slots["C1-B2"]["brand_id"] == "B2" and "성수 팝업" not in slots["C1-B2"]["reason"]


def test_budget_and_provider_failure_keep_existing_material(client, fakes, monkeypatch):
    pid, plan = setup_project(client)
    m = ok(client.post(f"/v1/projects/{pid}/materials", json={"title": "기존 수동 자료", "section_id": "campaign"}), 201)
    it = item(plan, "campaign", "경쟁Y")
    monkeypatch.setenv("RUN_BUDGET_USD", "0.001")
    job = ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [it["id"]]}), 202)["job"]
    res = ok(client.get(f"/v1/jobs/{job['id']}"))["result"]["items"][it["id"]]
    assert res["status"] == "blocked_budget" and fakes.calls.get("search", 0) == 0

    monkeypatch.setenv("RUN_BUDGET_USD", "5")
    fakes.fail_search = "PROVIDER_AUTH"
    job = ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [it["id"]]}), 202)["job"]
    res = ok(client.get(f"/v1/jobs/{job['id']}"))["result"]["items"][it["id"]]
    assert res["status"] == "failed" and res["errors"][0]["code"] == "PROVIDER_AUTH"
    assert [x["id"] for x in ok(client.get(f"/v1/projects/{pid}/materials"))] == [m["id"]]  # nothing deleted
    plan2 = ok(client.get(f"/v1/projects/{pid}/research-plan"))
    assert item(plan2, "campaign", "경쟁Y")["execution_status"] == "failed"


def test_influencer_urls_become_candidate_batch(client, fakes, monkeypatch):
    monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)  # isolate manual-URL handling from YouTube auto-discovery
    pid, plan = setup_project(client)
    it = item(plan, "influencer")
    bad = client.put(f"/v1/research-items/{it['id']}/inputs", json={"post_urls": ["https://example.com/x"]})
    assert bad.status_code == 422
    ok(client.put(f"/v1/research-items/{it['id']}/inputs", json={"post_urls": [
        "https://www.instagram.com/p/C1x/", "https://www.youtube.com/watch?v=vid1"]}))
    job = ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [it["id"]]}), 202)["job"]
    res = ok(client.get(f"/v1/jobs/{job['id']}"))["result"]["items"][it["id"]]
    assert res["status"] == "succeeded" and res["posts"] == 2
    batch = next(b for b in ok(client.get(f"/v1/projects/{pid}/imports")) if b["id"] == res["batch_id"])
    assert batch["status"] == "candidate" and batch["kind"] == "posts" and not batch["synthetic"]
    assert fakes.calls["youtube_channel"] == 1  # subscribers come from the channel endpoint
    assert fakes.calls["instagram_profile"] == 1  # Instagram followers come from the profile endpoint
    ok(client.post(f"/v1/imports/{batch['id']}/review", json={"action": "accept"}))
    sp = ok(client.get(f"/v1/projects/{pid}/slide-plan"))
    assert next(s for s in sp["plan"] if s["slot_id"] == "3-1-B1")["readiness"] == "ready"


def test_influencer_item_finds_posts_without_any_input(client, fakes, monkeypatch):
    """Phase 1-2: no post_urls, no hashtags — the brand name becomes the Instagram hashtag and the
    YouTube search term, Owned/Earned is split by official handle, and YouTube's native paid-promotion
    flag marks the sponsored post."""
    monkeypatch.setenv("APIFY_TOKEN", "test-token")

    def hashtag(tags, per_tag=60, **kw):
        fakes._hit("instagram_hashtag")
        assert tags == ["브랜드A", "브랜드 A"]  # 브랜드 이름 + 다른 표기로 자동 생성됨
        return CallResult(data={"posts": [
            {"url": "https://www.instagram.com/p/EARNED1/", "posted_at": "2026-08-10", "creator": "fit_runner",
             "likes": 400, "comments": 10, "views": None}]}, usage={"results": 1}, cost_usd=0.01)

    research.PROVIDERS["instagram_hashtag"] = hashtag
    pid, plan = setup_project(client)
    clear_cache()
    it = item(plan, "influencer")
    assert (it["inputs"] or {}).get("post_urls") in (None, []) and (it["inputs"] or {}).get("hashtags") in (None, [])
    job = ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [it["id"]]}), 202)["job"]
    res = ok(client.get(f"/v1/jobs/{job['id']}"))["result"]["items"][it["id"]]
    assert res["status"] == "succeeded" and res["posts"] == 2  # IG 해시태그 1건 + YouTube 검색 1건
    assert res["coverage_short"] is True  # 목표 10건에 한참 못 미침

    batch = next(b for b in ok(client.get(f"/v1/projects/{pid}/imports")) if b["id"] == res["batch_id"])
    ok(client.post(f"/v1/imports/{batch['id']}/review", json={"action": "accept"}))

    with SessionLocal() as db:
        rows = [r.data for r in db.scalars(select(PostRow).where(PostRow.project_id == pid))]
    ig_row = next(r for r in rows if r["channel"] == "instagram")
    yt_row = next(r for r in rows if r["channel"] == "youtube")
    assert ig_row["owner_type"] == "creator" and ig_row["sponsored"] is False
    assert yt_row["owner_type"] == "creator" and yt_row["sponsored"] is True  # isPaidPromotion=True in the fake


def test_influencer_item_marks_official_account_posts_as_self(client, fakes, monkeypatch):
    monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)  # isolate: only the manual URL matters here
    pid, plan = setup_project(client)
    proj = ok(client.get(f"/v1/projects/{pid}"))
    cfg = proj["config"]
    cfg["brands"][0]["official_profiles"] = [{"channel": "instagram", "url": "https://www.instagram.com/ig_creator/",
                                              "status": "confirmed"}]  # matches the fake instagram_post's creator
    ok(client.patch(f"/v1/projects/{pid}", json={"base_version": proj["version"], "changes": {"brands": cfg["brands"]}}))
    plan = ok(client.get(f"/v1/projects/{pid}/research-plan"))
    it = item(plan, "influencer")
    ok(client.put(f"/v1/research-items/{it['id']}/inputs", json={"post_urls": ["https://www.instagram.com/p/C1x/"]}))
    job = ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [it["id"]]}), 202)["job"]
    assert ok(client.get(f"/v1/jobs/{job['id']}"))["result"]["items"][it["id"]]["status"] == "succeeded"
    with SessionLocal() as db:
        row = db.scalars(select(PostRow).where(PostRow.project_id == pid)).one()
    assert row.data["owner_type"] == "self"  # 공식 계정이 올린 글이라 Owned


def test_search_items_auto_collect_via_naver(client, fakes):
    pid, plan = setup_project(client)
    it = item(plan, "search")
    job = ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [it["id"]]}), 202)["job"]
    res = ok(client.get(f"/v1/jobs/{job['id']}"))["result"]["items"][it["id"]]
    assert res["status"] == "succeeded" and res["facts"] > 0
    # 세트마다 데이터랩 요청 1회(12M·9M은 같은 응답에서 잘라 같은 scale_id): 브랜드명, 조합어 +가방,
    # 키 타겟(연령·성별 필터) 브랜드명, 키 타겟 조합어 +가방
    assert [x["label"] for x in res["sets"]] == ["브랜드명", "조합어 +가방", "키 타겟 · 브랜드명", "키 타겟 · 조합어 +가방"]
    assert fakes.calls["search_trend"] == 4

    facts = ok(client.get(f"/v1/projects/{pid}/facts"))
    assert facts and all(f["verification_status"] == "candidate" and f["origin"] == "auto" for f in facts)
    sums = [f for f in facts if f["metric"] == "search_group_sum"]
    assert {f["dims"]["window"] for f in sums} == {"12M", "9M"}
    assert {(f["dims"]["seg"], f["dims"].get("cat")) for f in sums} == {("all", None), ("all", "가방"), ("T", None), ("T", "가방")}
    monthly = [f for f in facts if f["metric"] == "search_index_monthly"]
    assert monthly and {f["dims"]["seg"] for f in monthly} == {"all"} and not any("cat" in f["dims"] for f in monthly)
    for f in facts:
        ok(client.patch(f"/v1/facts/{f['id']}/review?project_id={pid}", json={"action": "confirm"}))

    sp = ok(client.get(f"/v1/projects/{pid}/slide-plan"))
    for slot in ("2-8a", "2-8b", "2-8d"):
        assert next(s for s in sp["plan"] if s["slot_id"] == slot)["readiness"] == "ready", slot
    assert next(s for s in sp["plan"] if s["template_id"] == "2-8c")["readiness"] == "ready"


def test_search_item_counts_mentions_per_channel_without_calling_it_search_volume(client, fakes):
    """P2-4: 자사·경쟁사 × 블로그·카페글·뉴스·지식iN의 검색 결과 문서 수(누적) + 최근 3개월 블로그·뉴스 달별 수.
    카페글이 비활성이면 그 종류만 사유를 남기고 건너뛴다(오류 아님). 블로그는 1,000건 한도에 걸려 일부만 센 달 표시."""
    from core.ingestion.mentions import recent_months

    clear_cache()
    pid, plan = setup_project(client)
    it = item(plan, "search")
    assert "naver_mentions" in {c["id"] for c in it["channels"]}
    months = recent_months(date.today(), 3)
    newest = date.fromisoformat(f"{months[-1]}-15")
    fakes.naver_denied = {"cafearticle"}
    seen = []

    def naver_search(kind, query, *, display=100, start=1, sort="date", **kw):
        fakes._hit("naver_search")
        seen.append((kind, query, display, start, sort))
        if kind in fakes.naver_denied:
            raise ProviderError("PROVIDER_AUTH", "NAVER API HUB 앱에서 '카페글' 검색 API가 활성화되어 있지 않습니다", 401)
        total = {"blog": 5000, "news": 40, "kin": 7}[kind] + (1 if " " in query else 0)
        items = []
        if display == 100 and sort == "date":
            if kind == "blog":  # 하루 20건씩 — 1,000건(10쪽)으로는 최근 50일까지만 닿는다
                items = [{"title": "t", "url": f"https://blog.naver.com/x/{start + i}", "snippet": "",
                          "date": date.fromordinal(newest.toordinal() + 15 - (start - 1 + i) // 20).isoformat(),
                          "author": None, "author_url": None} for i in range(100)]
            elif start == 1:  # 뉴스는 이번 달 1건, 지난달 2건뿐
                items = [{"title": "t", "url": f"https://n.example/{i}", "snippet": "", "date": d, "author": None,
                          "author_url": None} for i, d in enumerate([f"{months[-1]}-03", f"{months[-2]}-20", f"{months[-2]}-02"])]
        return CallResult(data={"total": total, "items": items, "via": "api_hub"}, usage={"requests": 1}, cost_usd=0.0,
                          cost_is_estimate=False)
    research.PROVIDERS["naver_search"] = naver_search

    job = ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [it["id"]]}), 202)["job"]
    res = ok(client.get(f"/v1/jobs/{job['id']}"))["result"]["items"][it["id"]]
    assert res["status"] == "succeeded"
    assert "활성화" in res["mentions"]["unavailable"]["cafe"] and not res["mentions"]["errors"]
    assert sum(1 for c in seen if c[0] == "cafearticle") == 1  # 비활성 종류는 한 번만 묻는다

    facts = ok(client.get(f"/v1/projects/{pid}/facts"))
    totals = [f for f in facts if f["metric"] == "mention_total"]
    entities = {f["entity"] for f in totals}
    assert {"브랜드A", "경쟁X"} <= entities
    assert {f["dims"]["channel"] for f in totals} == {"blog", "news", "kin"}
    assert all(f["verification_status"] == "candidate" for f in totals)
    blog_a = {f["dims"]["keyword_group"]: f for f in totals if f["entity"] == "브랜드A" and f["dims"]["channel"] == "blog"}
    assert float(blog_a["brand"]["value"]) == 5000 and blog_a["brand"]["dims"]["keyword"] == "브랜드A"
    assert float(blog_a["brand+가방"]["value"]) == 5001 and blog_a["brand+가방"]["dims"]["keyword"] == "브랜드A 가방"
    assert all("검색량" not in (f["label"] or "") for f in totals)

    monthly = {(f["dims"]["channel"], f["dims"]["month"]): f for f in facts
               if f["metric"] == "mention_monthly" and f["entity"] == "브랜드A"}
    news = [float(monthly[("news", m)]["value"]) for m in months]
    assert news == [0, 2, 1] and not any("partial" in monthly[("news", m)]["dims"] for m in months)
    # 블로그: 최근 50일만 닿았다 — 가장 최근 달은 다 셌고, 그 앞 달은 일부(partial),
    # 가장 오래된 달은 하나도 닿지 못해 Fact를 만들지 않는다(0으로 남기지 않음)
    assert "partial" not in monthly[("blog", months[-1])]["dims"] and monthly[("blog", months[1])]["dims"]["partial"] == "1"
    assert ("blog", months[0]) not in monthly
    assert any("닿지 못함" in x for x in res["mentions"]["partial_months"])


def test_search_item_classifies_top_blog_posts_by_type(client, fakes):
    """P2-5: 브랜드명·대표 조합어마다 블로그 상위 30건을 유형별로 나누고 비중 Fact(n=30)와 근거 주소를 남긴다.
    본문은 모바일 주소로 받아 끝의 대가 표시·제휴 링크까지 본다. 확인 전(candidate)."""
    clear_cache()
    pid, plan = setup_project(client)
    it = item(plan, "search")
    assert "naver_blog_types" in {c["id"] for c in it["channels"]}
    bodies = (["몇 달 써 보니 바퀴가 튼튼해요"] * 15 + ["소정의 원고료를 받아 작성했습니다"] * 6
              + ["쿠팡 파트너스 활동의 일환으로 수수료를 제공받습니다"] * 6 + ["신상 입고 안내 매장 방문 환영"] * 3)
    fakes.naver_items = {"blog": [{"title": f"글 {i}", "url": f"https://blog.naver.com/u{i}/{100 + i}", "snippet": "요약",
                                   "date": "2026-05-01", "author": "블로거", "author_url": None} for i in range(30)]}

    def fetch_page(url, **kw):
        fakes._hit("fetch_page")
        i = int(url.rsplit("/", 1)[-1]) - 100
        text = "본문 " * 900 + bodies[i]  # 표시 문구가 글 끝에 있다
        return Page(url=url, final_url=url, title=f"글 {i}", text=text, content_hash=f"h{i}", published=None,
                    publisher=None, image_urls=[])
    research.PROVIDERS["fetch_page"] = fetch_page

    job = ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [it["id"]]}), 202)["job"]
    res = ok(client.get(f"/v1/jobs/{job['id']}"))["result"]["items"][it["id"]]
    bt = res["blog_types"]
    assert set(bt["keywords"]) == {"브랜드A", "브랜드A 가방"} and fakes.calls["blog_type_classify"] == 6  # 30건 ÷ 10 × 2
    assert bt["keywords"]["브랜드A"]["types"] == {"real_use": 15, "sponsored": 6, "shopping_affiliate": 6,
                                                "promo_template": 3, "other": 0}

    shares = [f for f in ok(client.get(f"/v1/projects/{pid}/facts")) if f["metric"] == "blog_type_share"]
    assert len(shares) == 10 and all(f["verification_status"] == "candidate" for f in shares)
    by = {(f["dims"]["keyword"], f["dims"]["type"]): f for f in shares}
    real = by[("브랜드A", "real_use")]
    assert float(real["value"]) == 50.0 and real["dims"]["n"] == "30" and real["entity"] == "브랜드A"
    assert float(by[("브랜드A", "other")]["value"]) == 0.0
    assert sum(float(by[("브랜드A", t)]["value"]) for t in ("real_use", "sponsored", "shopping_affiliate",
                                                           "promo_template", "other")) == 100.0


def test_blog_types_are_not_made_from_a_thin_sample(client, fakes):
    clear_cache()
    pid, plan = setup_project(client)
    it = item(plan, "search")
    fakes.naver_items = {"blog": [{"title": f"글 {i}", "url": f"https://blog.naver.com/u{i}/{i}", "snippet": "써 보니 좋아요",
                                   "date": None, "author": None, "author_url": None} for i in range(5)]}
    research.PROVIDERS["fetch_page"] = lambda url, **kw: (_ for _ in ()).throw(ProviderError("SOURCE_UNAVAILABLE", "x"))
    job = ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [it["id"]]}), 202)["job"]
    res = ok(client.get(f"/v1/jobs/{job['id']}"))["result"]["items"][it["id"]]
    assert res["blog_types"]["keywords"]["브랜드A"]["n"] == 5 and res["blog_types"]["keywords"]["브랜드A"]["fetched"] == 0
    assert any("5건" in n for n in res["blog_types"]["notes"])
    assert not [f for f in ok(client.get(f"/v1/projects/{pid}/facts")) if f["metric"] == "blog_type_share"]


def _set_brand(client, pid, **changes):
    proj = ok(client.get(f"/v1/projects/{pid}"))
    brands = [{**proj["config"]["brands"][0], **changes}, *proj["config"]["brands"][1:]]
    ok(client.patch(f"/v1/projects/{pid}", json={"base_version": proj["version"], "changes": {"brands": brands}}))
    return ok(client.get(f"/v1/projects/{pid}/research-plan"))


def test_search_without_target_or_categories_collects_only_what_it_can(client, fakes):
    clear_cache()  # 같은 데이터랩 요청은 하루 캐시 — 앞 테스트의 응답을 받지 않게
    pid, _ = setup_project(client)
    plan = _set_brand(client, pid, target=None, categories=[])
    it = item(plan, "search")
    job = ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [it["id"]]}), 202)["job"]
    res = ok(client.get(f"/v1/jobs/{job['id']}"))["result"]["items"][it["id"]]
    assert [x["label"] for x in res["sets"]] == ["브랜드명"] and fakes.calls["search_trend"] == 1
    gaps = {s["template_id"]: s for s in ok(client.get(f"/v1/projects/{pid}/slide-plan"))["plan"]
            if s["readiness"] == "needs_input"}
    # 확인 전 지수가 있으니 2-8a는 '채택 대기', 2-8c·2-8d는 설정이 비어 '설정 필요'와 고칠 곳
    assert gaps["2-8a"]["cause"] == "adopt" and "검색 지수" in gaps["2-8a"]["action"]
    assert gaps["2-8c"]["cause"] == "setup" and "카테고리" in gaps["2-8c"]["action"]
    assert gaps["2-8d"]["cause"] == "setup" and "키 타겟" in gaps["2-8d"]["action"]


def test_search_keeps_going_when_one_set_fails_but_stops_on_auth(client, fakes):
    clear_cache()
    pid, plan = setup_project(client)
    it = item(plan, "search")
    real = fakes.search_trend

    def flaky(groups, start, end, **kw):
        if any(" " in k for _, kws in groups for k in kws):  # 조합어 세트만 실패
            raise ProviderError("PROVIDER_ERROR", "Naver 오류 (500)", 500)
        return real(groups, start, end, **kw)
    research.PROVIDERS["naver_search_trend"] = flaky
    job = ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [it["id"]]}), 202)["job"]
    res = ok(client.get(f"/v1/jobs/{job['id']}"))["result"]["items"][it["id"]]
    assert [x["label"] for x in res["sets"]] == ["브랜드명", "키 타겟 · 브랜드명"]
    assert any(e["message"].startswith("조합어 +가방") for e in res["errors"])

    clear_cache()

    def denied(groups, start, end, **kw):
        raise ProviderError("PROVIDER_AUTH", "NAVER API HUB 앱에 '검색어트렌드' API가 선택되어 있지 않습니다", 401)
    research.PROVIDERS["naver_search_trend"] = denied
    calls_before = fakes.calls.get("search_trend", 0)
    job = ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [it["id"]]}), 202)["job"]
    res = ok(client.get(f"/v1/jobs/{job['id']}"))["result"]["items"][it["id"]]
    assert len(res["errors"]) == 1 and fakes.calls.get("search_trend", 0) == calls_before  # 첫 세트에서 멈춤


def test_search_items_need_naver_key(client, fakes, monkeypatch):
    monkeypatch.delenv("NAVER_CLIENT_ID", raising=False)
    monkeypatch.delenv("NAVER_CLIENT_SECRET", raising=False)
    pid, plan = setup_project(client)
    it = item(plan, "search")
    r = client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [it["id"]]})
    assert r.status_code == 503
    assert r.json()["error"]["detail"]["providers"] == ["naver"]


def test_search_trend_item_collects_monthly_index_and_related_queries(client, fakes):
    """Phase 3-4 검색 추이(Google Trends): 주별 응답을 월별로 평균해 자사·카테고리 지수로 남긴다."""
    pid, plan = setup_project(client)
    it = item(plan, "search_trend")
    assert it["role"] == "self"
    job = ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [it["id"]]}), 202)["job"]
    res = ok(client.get(f"/v1/jobs/{job['id']}"))["result"]["items"][it["id"]]
    assert res["status"] == "succeeded" and res["facts"] > 0
    assert res["related_queries"] == ["브랜드A 신상", "브랜드A 세일"]
    assert fakes.calls["google_trends_search"] == 1

    facts = [f for f in ok(client.get(f"/v1/projects/{pid}/facts")) if f["metric"] == "trends_index_monthly"]
    assert facts and {f["entity"] for f in facts} == {"브랜드A", "가방"}  # 브랜드명 + 카테고리
    assert all(f["dims"]["month"] == "2026-07" for f in facts)  # 네 번의 주간 응답이 한 달로 묶임
    assert all(f["verification_status"] == "candidate" and f["origin"] == "auto" for f in facts)
    for f in facts:
        ok(client.patch(f"/v1/facts/{f['id']}/review?project_id={pid}", json={"action": "confirm"}))

    # TR1 isn't in the sample project's curated demo slide list (like M1/M2) — turn it on explicitly.
    project = ok(client.get(f"/v1/projects/{pid}"))
    ok(client.patch(f"/v1/projects/{pid}", json={"base_version": project["version"],
                                                "changes": {"enabled_slides": project["config"]["enabled_slides"] + ["TR1"]}}))
    sp = ok(client.get(f"/v1/projects/{pid}/slide-plan"))
    tr1 = next(s for s in sp["plan"] if s["slot_id"] == "TR1")
    assert tr1["readiness"] == "thin" and "검색 경쟁 분석" in tr1["reason"]


def test_search_trend_item_tracks_every_product_category_not_just_one(client, fakes):
    """피드백 #1 축 2(품목별 검색량 분해): 카테고리마다(캐리어·백팩 등) 각자 검색 지수를 남긴다."""
    p = ok(client.post("/v1/projects", json={
        "name": "품목별 검색량 테스트", "client": "고객", "period": {"start": "2026-01-01", "end": "2026-09-30"},
        "brands": [{"id": "B1", "name": "브랜드A", "competitors": ["경쟁X"],
                   "categories": ["캐리어", "백팩", "브랜드A"]}]}), 201)  # 브랜드명과 같은 카테고리는 빠져야 함
    pid = p["id"]
    plan = ok(client.get(f"/v1/projects/{pid}/research-plan"))
    it = item(plan, "search_trend")
    job = ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [it["id"]]}), 202)["job"]
    res = ok(client.get(f"/v1/jobs/{job['id']}"))["result"]["items"][it["id"]]
    assert res["status"] == "succeeded"

    facts = [f for f in ok(client.get(f"/v1/projects/{pid}/facts")) if f["metric"] == "trends_index_monthly"]
    assert {f["entity"] for f in facts} == {"브랜드A", "캐리어", "백팩"}  # 브랜드명과 같은 카테고리는 중복 제외


def test_search_trend_item_fails_quietly_when_google_trends_blocks_it(client, fakes):
    """Phase 3-4: Trends가 막히면(흔함) 장표는 조용히 빠지고 원인은 '수집 필요'로 나온다."""
    clear_cache()  # avoid a cache hit from the earlier successful test (same keywords/geo request)
    fakes.fail_trends = True
    pid, plan = setup_project(client)
    it = item(plan, "search_trend")
    job = ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [it["id"]]}), 202)["job"]
    res = ok(client.get(f"/v1/jobs/{job['id']}"))["result"]["items"][it["id"]]
    # Trends만 막혔다 — 쇼핑인사이트(P2-2)는 모였으니 실패가 아니라 일부 성공
    assert res["status"] == "partial" and res["errors"][0]["code"] == "RATE_LIMITED"
    assert res["shopping"]["facts"] > 0

    # TR1 isn't in the sample project's curated demo slide list (like M1/M2) — turn it on explicitly.
    project = ok(client.get(f"/v1/projects/{pid}"))
    ok(client.patch(f"/v1/projects/{pid}", json={"base_version": project["version"],
                                                "changes": {"enabled_slides": project["config"]["enabled_slides"] + ["TR1"]}}))
    missing = {m["slot_id"]: m for m in ok(client.get(f"/v1/projects/{pid}/outline"))["missing"]}
    assert missing["TR1"]["cause"] == "collect"


def test_search_trend_item_collects_shopping_demand_by_product_category(client, fakes):
    """P2-2: 제품군마다 쇼핑 분야를 스스로 고르고, 월별 클릭 지수·성수기·연령/성별 비중을 확인 전 Fact로."""
    clear_cache()
    pid, plan = setup_project(client)
    it = item(plan, "search_trend")
    assert "shopping_insight" in [c["id"] for c in it["channels"]]
    job = ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [it["id"]]}), 202)["job"]
    res = ok(client.get(f"/v1/jobs/{job['id']}"))["result"]["items"][it["id"]]
    assert res["status"] == "succeeded"
    assert res["shopping"]["categories"] == {"가방": "패션잡화"}  # 가짜 데이터는 패션잡화에만 클릭이 있다
    assert fakes.calls["shopping_keyword_trend"] == 10 + 1  # 분야 10개 대조 + 고른 분야 추이 1회
    assert fakes.calls["shopping_keyword_breakdown"] == 2  # 제품군 1개 × 연령·성별

    facts = [f for f in ok(client.get(f"/v1/projects/{pid}/facts")) if f["metric"].startswith("shop_")]
    assert all(f["verification_status"] == "candidate" and f["origin"] == "auto" for f in facts)
    index = [f for f in facts if f["metric"] == "shop_click_index"]
    assert len(index) == 12 and {f["entity"] for f in index} == {"가방"} and index[0]["dims"]["category"] == "50000001"
    peaks = sorted(f["dims"]["month"][5:] for f in facts if f["metric"] == "shop_peak_lift")
    assert peaks == ["07", "08"]
    shares = {(f["dims"]["by"], f["dims"]["group"]): float(f["value"]) for f in facts if f["metric"] == "shop_click_share"}
    assert shares == {("age", "20"): 30.0, ("age", "30"): 50.0, ("age", "40"): 20.0, ("gender", "f"): 60.0,
                      ("gender", "m"): 40.0}


def test_commerce_review_item_collects_rating_and_keywords_excluding_sponsored(client, fakes, monkeypatch):
    """Phase 2 커머스 리뷰: 확정된 대표 상품의 평점·리뷰 수·긍정부정 키워드를 모은다(체험단 리뷰는 집계에서 뺌)."""
    from app.models import ReviewKeyword, ReviewSnapshot
    from integrations.commerce import musinsa

    p = ok(client.post("/v1/projects", json={
        "name": "커머스 리뷰 테스트", "client": "고객", "period": {"start": "2026-01-01", "end": "2026-09-30"},
        "brands": [{"id": "B1", "name": "브랜드A", "competitors": ["경쟁X"], "categories": ["신발"], "industry": "패션",
                   "hero_products": [{"name": "에어맥스 95", "status": "confirmed"}]}]}), 201)
    pid = p["id"]
    plan = ok(client.get(f"/v1/projects/{pid}/research-plan"))
    it = item(plan, "commerce_review", "브랜드A")
    assert it["role"] == "self"

    mute_other_commerce_platforms(monkeypatch)
    monkeypatch.setattr(musinsa, "find_product",
                        lambda name, **kw: {"id": "123", "url": "https://www.musinsa.com/products/123"})
    monkeypatch.setattr(musinsa, "fetch_product", lambda product_id, **kw: {
        "platform": "musinsa", "product_name": "에어맥스 95", "product_url": "https://www.musinsa.com/products/123",
        "brand_name": "나이키", "rating": 4.5, "rating_scale": 5.0, "review_count": 120, "access_status": "ok"})
    monkeypatch.setattr(musinsa, "fetch_reviews", lambda product_id, **kw: [
        {"text": "쿠션감이 좋아요 재구매 의사 있습니다", "rating": 5, "posted_at": "2026-08-01", "sponsored": False},
        {"text": "쿠션감이 부족해서 별로예요", "rating": 2, "posted_at": "2026-08-02", "sponsored": False},
        {"text": "체험단으로 제공받아 작성한 후기입니다. 쿠션감이 좋아요", "rating": 5, "posted_at": "2026-08-03", "sponsored": True},
    ])

    job = ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [it["id"]]}), 202)["job"]
    res = ok(client.get(f"/v1/jobs/{job['id']}"))["result"]["items"][it["id"]]
    assert res["status"] == "succeeded" and res["snapshots"] == 1

    with SessionLocal() as db:
        snaps = db.scalars(select(ReviewSnapshot).where(ReviewSnapshot.project_id == pid)).all()
        # 무신사 1건(평점 확보) + 나머지 4개 플랫폼은 '찾지 못함'으로 접근 불가 — 플랫폼마다 한 행.
        assert len(snaps) == 5
        others = [s for s in snaps if s.platform != "musinsa"]
        assert all(s.access_status == "unavailable" for s in others)
        snap = next(s for s in snaps if s.platform == "musinsa")
        assert snap.rating == 4.5 and snap.review_count == 120 and snap.review_status == "candidate"
        assert snap.sponsored_count == 1  # 체험단 리뷰 1건은 따로 셈
        kws = db.scalars(select(ReviewKeyword).where(ReviewKeyword.snapshot_id == snap.id)).all()
        by_sentiment = {k.sentiment: k for k in kws}
        assert set(by_sentiment) == {"positive", "negative"}
        assert by_sentiment["positive"].sample_size == 1  # 체험단 리뷰는 키워드 집계에서 빠짐(2건이 아니라 1건)
        assert by_sentiment["negative"].blocks_purchase is True
        assert by_sentiment["negative"].quotes[0]["posted_at"] == "2026-08-02"


def test_commerce_review_item_checks_every_platform_and_one_blocked_platform_does_not_abort_others(client, fakes, monkeypatch):
    """Phase 2 커머스 리뷰: 대표 상품마다 연동된 플랫폼 5개를 전부 돈다 — 한 플랫폼이 차단돼도
    (ProviderError) 그 플랫폼만 접근 불가로 남고 나머지는 계속 수집한다(항목 전체 실패 아님)."""
    from app.models import ReviewSnapshot
    from integrations.base import ProviderError
    from integrations.commerce import coupang, musinsa, oliveyoung, smartstore, twentyninecm

    p = ok(client.post("/v1/projects", json={
        "name": "멀티 플랫폼 테스트", "client": "고객", "period": {"start": "2026-01-01", "end": "2026-09-30"},
        "brands": [{"id": "B1", "name": "브랜드A", "competitors": ["경쟁X"], "categories": ["신발"], "industry": "패션",
                   # 다른 테스트와 같은 (플랫폼, 상품명) 조합을 쓰면 7일 캐시(ledger.call)를 맞고 지나간다.
                   "hero_products": [{"name": "멀티플랫폼용 상품", "status": "confirmed"}]}]}), 201)
    pid = p["id"]
    plan = ok(client.get(f"/v1/projects/{pid}/research-plan"))
    it = item(plan, "commerce_review", "브랜드A")

    monkeypatch.setattr(musinsa, "find_product",
                        lambda name, **kw: {"id": "123", "url": "https://www.musinsa.com/products/123"})
    monkeypatch.setattr(musinsa, "fetch_product", lambda product_id, **kw: {
        "platform": "musinsa", "product_name": "에어맥스 95", "product_url": "https://www.musinsa.com/products/123",
        "rating": 4.5, "rating_scale": 5.0, "review_count": 120, "access_status": "ok"})
    monkeypatch.setattr(musinsa, "fetch_reviews", lambda product_id, **kw: [])

    def blocked(name, **kw):  # 29CM처럼 검색 자체가 막힌 경우를 흉내
        raise ProviderError("SOURCE_UNAVAILABLE", "29CM 접근 실패 (403)", 403)

    monkeypatch.setattr(twentyninecm, "find_product", blocked)
    monkeypatch.setattr(oliveyoung, "find_product", lambda name, **kw: None)  # 찾지 못함(차단 아님)
    monkeypatch.setattr(smartstore, "find_product", lambda name, **kw: None)
    monkeypatch.setattr(coupang, "find_product", lambda name, **kw: None)

    job = ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [it["id"]]}), 202)["job"]
    res = ok(client.get(f"/v1/jobs/{job['id']}"))["result"]["items"][it["id"]]
    assert res["status"] == "succeeded" and res["snapshots"] == 1  # 무신사만 평점 확보, 항목은 성공

    with SessionLocal() as db:
        snaps = {s.platform: s for s in db.scalars(select(ReviewSnapshot).where(ReviewSnapshot.project_id == pid))}
        assert set(snaps) == {"musinsa", "29cm", "oliveyoung", "smartstore", "coupang"}
        assert snaps["musinsa"].access_status == "ok" and snaps["musinsa"].rating == 4.5
        assert snaps["29cm"].access_status == "unavailable" and "403" in snaps["29cm"].reason
        assert snaps["oliveyoung"].access_status == "unavailable" and snaps["oliveyoung"].reason == "검색 결과에서 상품을 찾지 못함"


def test_commerce_review_item_requires_a_confirmed_hero_product(client, fakes):
    """대표 상품을 확정하지 않으면 수집하지 않는다(자동 채택 금지의 연장)."""
    p = ok(client.post("/v1/projects", json={
        "name": "대표 상품 없음", "client": "고객", "period": {"start": "2026-01-01", "end": "2026-09-30"},
        "brands": [{"id": "B1", "name": "브랜드A", "competitors": ["경쟁X"], "industry": "패션"}]}), 201)
    pid = p["id"]
    plan = ok(client.get(f"/v1/projects/{pid}/research-plan"))
    it = item(plan, "commerce_review", "브랜드A")
    job = ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [it["id"]]}), 202)["job"]
    res = ok(client.get(f"/v1/jobs/{job['id']}"))["result"]["items"][it["id"]]
    assert res["status"] == "failed" and res["errors"][0]["code"] == "NO_PRODUCT"


def test_commerce_review_needs_adoption_then_appears_on_cm1_once_accepted(client, fakes, monkeypatch):
    """Phase 2 커머스 리뷰: 수집 직후엔 '채택 대기'로 뜨고, 사람이 채택해야 CM1에 실린다(자동 채택 금지)."""
    from integrations.commerce import musinsa

    p = ok(client.post("/v1/projects", json={
        "name": "커머스 리뷰 채택 테스트", "client": "고객", "period": {"start": "2026-01-01", "end": "2026-09-30"},
        "brands": [{"id": "B1", "name": "브랜드A", "competitors": ["경쟁X"], "categories": ["신발"], "industry": "패션",
                   "hero_products": [{"name": "에어맥스 95", "status": "confirmed"}]}]}), 201)
    pid = p["id"]
    plan = ok(client.get(f"/v1/projects/{pid}/research-plan"))
    it = item(plan, "commerce_review", "브랜드A")

    mute_other_commerce_platforms(monkeypatch)
    monkeypatch.setattr(musinsa, "find_product",
                        lambda name, **kw: {"id": "123", "url": "https://www.musinsa.com/products/123"})
    monkeypatch.setattr(musinsa, "fetch_product", lambda product_id, **kw: {
        "platform": "musinsa", "product_name": "에어맥스 95", "product_url": "https://www.musinsa.com/products/123",
        "brand_name": "나이키", "rating": 4.5, "rating_scale": 5.0, "review_count": 120, "access_status": "ok"})
    monkeypatch.setattr(musinsa, "fetch_reviews", lambda product_id, **kw: [
        {"text": "쿠션감이 좋아요 재구매 의사 있습니다", "rating": 5, "posted_at": "2026-08-01", "sponsored": False},
    ])
    job = ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [it["id"]]}), 202)["job"]
    assert ok(client.get(f"/v1/jobs/{job['id']}"))["result"]["items"][it["id"]]["status"] == "succeeded"

    project = ok(client.get(f"/v1/projects/{pid}"))
    ok(client.patch(f"/v1/projects/{pid}", json={"base_version": project["version"],
                                                "changes": {"enabled_slides": project["config"]["enabled_slides"] + ["CM1"]}}))
    missing = {m["slot_id"]: m for m in ok(client.get(f"/v1/projects/{pid}/outline"))["missing"]}
    assert missing["CM1"]["cause"] == "adopt"  # 모은 스냅샷이 채택을 기다리는 중

    snaps = ok(client.get(f"/v1/projects/{pid}/review-snapshots"))
    # 무신사 1건(평점 확보) + 나머지 4개 플랫폼은 '찾지 못함'으로 접근 불가 — 플랫폼마다 한 행.
    assert len(snaps) == 5 and all(s["review_status"] == "candidate" for s in snaps)
    snap = next(s for s in snaps if s["platform"] == "musinsa")
    ok(client.patch(f"/v1/review-snapshots/{snap['id']}/review", json={"status": "accepted"}))
    for kw in snap["keywords"]:
        ok(client.patch(f"/v1/review-keywords/{kw['id']}/review", json={"status": "accepted"}))

    sp = ok(client.get(f"/v1/projects/{pid}/slide-plan"))
    assert next(s for s in sp["plan"] if s["slot_id"] == "CM1")["readiness"] == "ready"


def test_deck_build_asks_before_building_with_pending_review(client, fakes):
    """Phase 3-5: 확인 대기 자료가 있으면 그냥 만들지 않고 묻는다 — 확인하면 그대로 진행하고 감사 기록을 남긴다."""
    from app.models import AuditLog

    pid, plan = setup_project(client)
    it = item(plan, "campaign", "경쟁X")
    job = ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [it["id"]]}), 202)["job"]
    assert ok(client.get(f"/v1/jobs/{job['id']}"))["state"] == "succeeded"
    mats = ok(client.get(f"/v1/projects/{pid}/materials"))
    assert any(m["review_status"] == "candidate" for m in mats)  # 아직 아무것도 채택하지 않음

    r = client.post(f"/v1/projects/{pid}/deck-builds")
    assert r.status_code == 409
    err = r.json()["error"]
    assert err["code"] == "PENDING_REVIEW" and err["detail"]["pending"] > 0

    out = ok(client.post(f"/v1/projects/{pid}/deck-builds", json={"confirm_pending": True}), 202)
    assert ok(client.get(f"/v1/jobs/{out['job']['id']}"))["state"] == "succeeded"
    with SessionLocal() as db:
        row = db.scalars(select(AuditLog).where(AuditLog.project_id == pid,
                                                AuditLog.action == "build_with_pending_review")).one()
        assert row.after["pending"] > 0


def test_deck_build_recollects_missing_items_before_building(client, fakes):
    """Phase 3-5: 만들기 전에, 원인이 '수집 필요'인 항목만 한 번 더 자동으로 수집을 시도한다."""
    pid, plan = setup_project(client)
    it = item(plan, "campaign", "경쟁X")
    assert it["execution_status"] == "not_started"

    out = ok(client.post(f"/v1/projects/{pid}/deck-builds"), 202)
    assert ok(client.get(f"/v1/jobs/{out['job']['id']}"))["state"] == "succeeded"

    again = item(ok(client.get(f"/v1/projects/{pid}/research-plan")), "campaign", "경쟁X")
    assert again["execution_status"] == "succeeded"  # 만들기 전에 자동으로 한 번 수집을 시도함
    mats = ok(client.get(f"/v1/projects/{pid}/materials"))
    assert any(m["source"]["url"] == "https://news.example.com/a1" for m in mats)


def test_lead_proposal_rewrite_then_accept(client, fakes):
    pid, _ = setup_project(client)
    for b in ok(client.post(f"/v1/projects/{pid}/imports/sample"), 201):
        ok(client.post(f"/v1/imports/{b['id']}/review", json={"action": "accept"}))
    job = ok(client.post(f"/v1/projects/{pid}/insight-proposals", json={"slide_ids": ["2-8a"]}), 202)["job"]
    assert ok(client.get(f"/v1/jobs/{job['id']}"))["state"] == "succeeded"
    props = ok(client.get(f"/v1/projects/{pid}/insight-proposals"))
    lp = next(p for p in props if p["slide_id"] == "2-8a")
    assert lp["status"] == "pending" and lp["attempts"] == 2  # first answer had a bare number
    assert any(p["type"] == "fact" for para in lp["parts"]["evidence"] for p in para["parts"])
    ok(client.post(f"/v1/insight-proposals/{lp['id']}/review", json={"action": "accept"}))
    sp = ok(client.get(f"/v1/projects/{pid}/slide-plan"))
    assert not [i for i in sp["qc"]["issues"] if i["slide_id"] == "2-8a" and i["severity"] == "block"]
    # The rule lead comes back when the override is cleared.
    ok(client.delete(f"/v1/projects/{pid}/lead-overrides/2-8a"))


def test_deck_build_writes_claim_evidence_and_page_insights_once_per_page_body(client, fakes):
    """P3-4/5: deck builds cache evidence-backed headlines and three page insights per unchanged body."""
    from app.models import SlideWriting

    pid, _ = setup_project(client)
    for b in ok(client.post(f"/v1/projects/{pid}/imports/sample"), 201):
        ok(client.post(f"/v1/imports/{b['id']}/review", json={"action": "accept"}))
    clear_cache()
    out = ok(client.post(f"/v1/projects/{pid}/deck-builds"), 202)
    job = ok(client.get(f"/v1/jobs/{out['job']['id']}"))
    assert job["state"] == "succeeded" and job["result"]["writing"]["lead"]["written"] > 0
    assert job["result"]["writing"]["insights"]["written"] > 0
    deck = ok(client.get(f"/v1/projects/{pid}/decks"))[0]
    slide = next(s for s in ok(client.get(f"/v1/decks/{deck['id']}"))["spec"]["slides"] if s["slide_id"] == "2-8a")
    ev = next(b for b in slide["blocks"] if b.get("role") == "lead_evidence")
    assert ev["block_id"] == "lead_evidence" and any(p["type"] == "fact" for para in ev["paragraphs"] for p in para["parts"])
    claim = next(b for b in slide["blocks"] if b.get("role") == "lead")
    assert any(p.get("color") == "accent" for para in claim["paragraphs"] for p in para["parts"])
    cards = [b for b in slide["blocks"] if b.get("role") == "insight" and b["block_id"].endswith("_body")]
    assert len(cards) == 3 and all(any(p["type"] == "fact" for p in b["paragraphs"][0]["parts"]) for b in cards)
    fact = next(part for part in cards[0]["paragraphs"][0]["parts"] if part["type"] == "fact")
    override = {"insights": [
        {"title": {"parts": [{"type": "text", "text": title}]},
         "body_segments": {"parts": [{"type": "text", "text": body}, fact]}}
        for title, body in [("사람 확인", "직접 고친 값 "), ("격차 확인", "비교할 값 "), ("다음 확인", "운영할 값 ")]
    ]}
    saved = ok(client.put(f"/v1/projects/{pid}/insight-overrides/2-8a", json=override))
    assert saved["slide_id"] == "2-8a" and len(saved["insights"]) == 3
    assert "2-8a" not in ok(client.delete(f"/v1/projects/{pid}/insight-overrides/2-8a"))["insight_overrides"]
    with SessionLocal() as db:
        rows = {row.kind: row for row in db.scalars(select(SlideWriting).where(
            SlideWriting.project_id == pid, SlideWriting.slide_id == "2-8a"))}
        assert rows["lead"].status == "ok" and rows["lead"].attempts == 2  # the first answer broke the rules
        assert rows["insights"].status == "ok" and len(rows["insights"].data["insights"]) == 3
    qc = ok(client.get(f"/v1/projects/{pid}/slide-plan"))["qc"]
    assert not [i for i in qc["issues"] if i["severity"] == "block" and i["slide_id"] == "2-8a"]

    def lead_calls():
        return sum(1 for r in ledger_rows(pid) if r.endpoint == "lead")

    def insight_calls():
        return sum(1 for r in ledger_rows(pid) if r.endpoint == "page_insights")

    before, before_insights = lead_calls(), insight_calls()
    out = ok(client.post(f"/v1/projects/{pid}/deck-builds", json={"confirm_pending": True}), 202)
    job = ok(client.get(f"/v1/jobs/{out['job']['id']}"))
    assert job["result"]["writing"]["lead"]["written"] == 0 and lead_calls() == before
    assert job["result"]["writing"]["insights"]["written"] == 0 and insight_calls() == before_insights


def test_same_activity_from_two_outlets_becomes_one_card(client, fakes):
    """Two articles about one campaign (same press image) -> one card plus an extra source, no second AI call."""
    pid, plan = setup_project(client)
    it = item(plan, "campaign", "경쟁X")

    def search(queries, **kw):
        fakes._hit("search")
        return CallResult(data={"id": "s2", "results": [
            {"title": "경쟁X, 일러스트레이터 키크니와 협업 이벤트 진행", "url": "https://a.example.com/1", "snippet": "", "date": "2026-02-07"},
            {"title": "경쟁X, 인기 작가 키크니와 직장인 공감 캠페인 전개 - TENANT news", "url": "https://b.example.com/2", "snippet": "", "date": "2026-02-04"},
        ]}, cost_usd=0.005)

    def fetch_page(url, **kw):
        fakes._hit("fetch_page")
        title = "경쟁X, 일러스트레이터 키크니와 협업 이벤트 진행" if "a.example" in url else "경쟁X, 인기 작가 키크니와 직장인 공감 캠페인 전개"
        return Page(url=url, final_url=url, title=title, text=ARTICLE, content_hash=url, published=None, publisher=None,
                    image_urls=["https://img.example.com/press.png"])

    research.PROVIDERS.update(search=search, fetch_page=fetch_page)
    with SessionLocal() as db:  # other tests cached the same search request
        db.query(ProviderCache).delete()
        db.commit()
    job = ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [it["id"]]}), 202)["job"]
    res = ok(client.get(f"/v1/jobs/{job['id']}"))["result"]["items"][it["id"]]
    assert res["created"] == 2 and res["duplicates"] == 1
    assert fakes.calls["structured"] == 1  # the duplicate skipped AI extraction

    mats = ok(client.get(f"/v1/projects/{pid}/materials"))
    primary = next(m for m in mats if m["source"]["url"] == "https://a.example.com/1")
    extra = next(m for m in mats if m["source"]["url"] == "https://b.example.com/2")
    assert primary["duplicate_of"] is None and [d["id"] for d in primary["duplicates"]] == [extra["id"]]
    assert extra["duplicate_of"] == primary["id"] and extra["duplicate_reason"] == "같은 대표 이미지"
    assert ok(client.get(f"/v1/projects/{pid}/research-plan"))["items"][it["order"] - 1]["coverage"]["duplicates"] == 1

    # An extra source cannot be accepted on its own.
    r = client.patch(f"/v1/materials/{extra['id']}/review", json={"status": "accepted"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "IS_DUPLICATE"

    # Swap the primary: the acceptance moves with it.
    ok(client.patch(f"/v1/materials/{primary['id']}/review", json={"status": "accepted"}))
    swapped = ok(client.post(f"/v1/materials/{extra['id']}/duplicate", json={"make_primary": True}))
    assert swapped["duplicate_of"] is None and swapped["review_status"] == "accepted"
    old = ok(client.get(f"/v1/materials/{primary['id']}"))
    assert old["duplicate_of"] == extra["id"] and old["review_status"] == "candidate"

    # Split it off: a later scan does not merge it back.
    ok(client.post(f"/v1/materials/{primary['id']}/duplicate", json={"of": None}))
    assert ok(client.post(f"/v1/projects/{pid}/materials/dedupe"))["merged"] == []
    assert ok(client.get(f"/v1/materials/{primary['id']}"))["duplicate_of"] is None

    # Merge by hand.
    merged = ok(client.post(f"/v1/materials/{primary['id']}/duplicate", json={"of": extra["id"]}))
    assert merged["duplicate_of"] == extra["id"]


def test_dedupe_scan_groups_existing_manual_cards(client, fakes):
    pid, _ = setup_project(client)
    body = {"section_id": "campaign", "entity": "경쟁X", "brand_id": "B1"}
    a = ok(client.post(f"/v1/projects/{pid}/materials", json={**body, "title": "경쟁X 넥시스 팝업 성수 오픈", "activity_date": "2026-07-10"}), 201)
    b = ok(client.post(f"/v1/projects/{pid}/materials", json={**body, "title": "경쟁X, 성수서 넥시스 체험 팝업", "activity_date": "2026-07-12"}), 201)
    c = ok(client.post(f"/v1/projects/{pid}/materials", json={**body, "title": "경쟁X 여름 할인 프로모션", "activity_date": "2026-07-11"}), 201)
    merged = ok(client.post(f"/v1/projects/{pid}/materials/dedupe"))["merged"]
    assert [(x["id"], x["primary_id"]) for x in merged] == [(b["id"], a["id"])]
    assert ok(client.get(f"/v1/materials/{c['id']}"))["duplicate_of"] is None


def test_patch_material_with_dates_is_audited(client, fakes):
    pid, _ = setup_project(client)
    m = ok(client.post(f"/v1/projects/{pid}/materials", json={"title": "날짜 있는 자료", "activity_date": "2026-03-01",
                                                               "published_at": "2026-03-02", "url": "https://e.com/a"}), 201)
    m2 = ok(client.patch(f"/v1/materials/{m['id']}", json={"base_version": m["version"], "title": "새 제목"}))
    assert m2["title"] == "새 제목"


def test_runs_overlap_unless_they_share_an_item(client, fakes):
    """Two research runs can be in flight together; the same item cannot be researched twice at once."""
    from app.models import Job
    pid, plan = setup_project(client)
    a, b = item(plan, "campaign", "경쟁X"), item(plan, "campaign", "경쟁Y")
    with SessionLocal() as db:  # a run that is still going for item a
        db.add(Job(id="JOB-busy", project_id=pid, kind="research_run", state="running", params={"item_ids": [a["id"]]},
                   project_version=1))
        db.commit()
    try:
        r = client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [a["id"]]})
        assert r.status_code == 409 and r.json()["error"]["detail"]["item_ids"] == [a["id"]]
        job = ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [b["id"]]}), 202)["job"]
        assert ok(client.get(f"/v1/jobs/{job['id']}"))["state"] == "succeeded"
    finally:
        with SessionLocal() as db:
            db.get(Job, "JOB-busy").state = "cancelled"
            db.commit()


def test_items_of_one_run_are_researched_in_parallel(client, fakes, monkeypatch):
    import threading
    import time
    pid, plan = setup_project(client)
    ids = [item(plan, "campaign", e)["id"] for e in ("경쟁X", "경쟁Y")]
    with SessionLocal() as db:
        db.query(ProviderCache).delete()
        db.commit()
    active, peak, lock = [0], [0], threading.Lock()
    original = fakes.search

    def slow_search(queries, **kw):
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        time.sleep(0.3)
        with lock:
            active[0] -= 1
        res = original(queries, **kw)
        tag = "x" if "경쟁X" in queries[0] else "y"  # each item finds its own articles, naming its own brand
        name = "경쟁X" if tag == "x" else "경쟁Y"
        res.data = {**res.data, "results": [{**r, "url": r["url"] + f"?{tag}", "title": r["title"].replace("경쟁X", name)}
                                            for r in res.data["results"]]}
        return res

    research.PROVIDERS["search"] = slow_search
    job = ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": ids}), 202)["job"]
    res = ok(client.get(f"/v1/jobs/{job['id']}"))
    assert res["state"] == "succeeded" and all(res["result"]["items"][i]["status"] in ("succeeded", "partial") for i in ids)
    assert peak[0] >= 2  # both items were searching at the same time


def test_interrupted_run_releases_its_items(client, fakes):
    """A run killed by a server restart must not leave its items locked as 'running'."""
    from app.jobs import recover_orphans
    from app.models import Job, ResearchItem
    pid, plan = setup_project(client)
    it = item(plan, "campaign", "경쟁X")
    with SessionLocal() as db:
        db.add(Job(id="JOB-dead", project_id=pid, kind="research_run", state="running", params={"item_ids": [it["id"]]},
                   project_version=1))
        row = db.get(ResearchItem, it["id"])
        row.execution_status, row.latest_job_id = "running", "JOB-dead"
        db.commit()
    recover_orphans()
    after = next(i for i in ok(client.get(f"/v1/projects/{pid}/research-plan"))["items"] if i["id"] == it["id"])
    assert after["execution_status"] == "failed" and after["last_result"]["errors"][0]["code"] == "WORKER_RESTARTED"


def test_plan_regeneration_keeps_item_inputs(client, fakes):
    """Saving project settings regenerates the plan; the post URLs a person entered must survive."""
    pid, plan = setup_project(client)
    it = item(plan, "influencer")
    ok(client.put(f"/v1/research-items/{it['id']}/inputs", json={"post_urls": ["https://www.youtube.com/watch?v=vid1"]}))
    project = ok(client.get(f"/v1/projects/{pid}"))
    ok(client.patch(f"/v1/projects/{pid}", json={"base_version": project["version"],
                                                "changes": {"enabled_slides": project["config"]["enabled_slides"] + ["M1"]}}))
    again = item(ok(client.get(f"/v1/projects/{pid}/research-plan")), "influencer")
    assert again["id"] != it["id"] and again["inputs"]["post_urls"] == ["https://www.youtube.com/watch?v=vid1"]


def test_research_keeps_to_the_period(client, fakes):
    """Search carries a publish-date window; far-off results are not fetched; an activity outside the
    period is excluded with a reason; the period check re-applies the rule to existing cards."""
    from datetime import date, timedelta

    pid, plan = setup_project(client)
    it = item(plan, "campaign", "경쟁X")
    start, end = date.fromisoformat(it["period_start"]), date.fromisoformat(it["period_end"])
    seen = {}

    def search(queries, **kw):
        fakes._hit("search")
        seen.setdefault("calls", []).append(kw)
        return CallResult(data={"id": "s3", "results": [
            {"title": "경쟁X 기간 안 팝업", "url": "https://p.example.com/in", "snippet": "", "date": str(start + timedelta(days=20))},
            {"title": "경쟁X 오래된 기사", "url": "https://p.example.com/old", "snippet": "", "date": str(start - timedelta(days=400))},
            {"title": "경쟁X 지난해 겨울 한정판 회고 인터뷰", "url": "https://q.example.org/past", "snippet": "", "date": str(start + timedelta(days=90))},
        ]}, cost_usd=0.005)

    def structured(system, user, schema, **kw):
        if "facts" not in schema["properties"]:
            return fakes.structured(system, user, schema, **kw)
        fakes._hit("structured")
        past = "q.example.org/past" in user
        act = start - timedelta(days=200) if past else start + timedelta(days=15)
        return CallResult(data={"relevant": not past, "relevance_note": "작년 활동" if past else "", "activity_date": str(act),
                                "activity_date_end": None, "event_name": "팝업", "same_as": None, "facts": [], "claims": []},
                          usage={"input_tokens": 10, "output_tokens": 10, "model": "fake"}, cost_usd=0.001, cost_is_estimate=False)

    def fetch_page(url, **kw):
        fakes._hit("fetch_page")
        return Page(url=url, final_url=url, title=url, text=ARTICLE, content_hash=url, published=None, publisher=None, image_urls=[])

    research.PROVIDERS.update(search=search, structured=structured, fetch_page=fetch_page)
    with SessionLocal() as db:
        db.query(ProviderCache).delete()
        db.commit()
    job = ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [it["id"]]}), 202)["job"]
    res = ok(client.get(f"/v1/jobs/{job['id']}"))["result"]["items"][it["id"]]
    calls = seen["calls"]  # the period is searched in parts that together span lead..tail
    assert len(calls) == 3
    assert calls[0]["published_after"] == (start - timedelta(days=30)).strftime("%m/%d/%Y")
    assert calls[-1]["published_before"] == (end + timedelta(days=14)).strftime("%m/%d/%Y")
    assert res["created"] == 2 and res["out_of_period"] == 2  # one never fetched, one excluded after extraction

    mats = {m["source"]["url"]: m for m in ok(client.get(f"/v1/projects/{pid}/materials"))}
    assert "https://p.example.com/old" not in mats
    assert mats["https://p.example.com/in"]["review_status"] == "candidate"
    past = mats["https://q.example.org/past"]
    assert past["review_status"] == "excluded" and past["review_reason"].startswith("조사 기간 밖")

    # Correcting the date and re-checking brings it back; the rule never touches reviewed cards.
    ok(client.patch(f"/v1/materials/{past['id']}", json={"base_version": past["version"], "activity_date": str(start + timedelta(days=5))}))
    out = ok(client.post(f"/v1/projects/{pid}/materials/period-check"))
    assert out["checked"] >= 2 and out["excluded"] == []
    assert ok(client.get(f"/v1/materials/{past['id']}"))["review_status"] == "candidate"


def test_hashtag_discovery_adds_in_period_creator_posts(client, fakes, monkeypatch):
    """Apify finds posts by hashtag; only in-period, non-official posts are added, best engagement first,
    and their metrics are then collected like hand-picked URLs."""
    from datetime import date, timedelta

    monkeypatch.setenv("APIFY_TOKEN", "test-token")
    monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)  # isolate hashtag discovery from YouTube auto-discovery
    pid, plan = setup_project(client)
    it = item(plan, "influencer")
    start = date.fromisoformat(it["period_start"])
    day = str(start + timedelta(days=30))

    def hashtag(tags, per_tag=60, **kw):
        fakes._hit("instagram_hashtag")
        posts = [
            {"url": "https://www.instagram.com/p/AAA/", "posted_at": day, "creator": "runner_kim", "likes": 900, "comments": 40, "views": None},
            {"url": "https://www.instagram.com/p/BBB/", "posted_at": day, "creator": "small_fit", "likes": 30, "comments": 2, "views": None},
            {"url": "https://www.instagram.com/p/CCC/", "posted_at": day, "creator": "brand1_official", "likes": 5000, "comments": 300, "views": None},
            {"url": "https://www.instagram.com/p/DDD/", "posted_at": str(start - timedelta(days=90)), "creator": "old_post", "likes": 9000, "comments": 900, "views": None},
        ]
        return CallResult(data={"posts": posts}, usage={"results": len(posts)}, cost_usd=0.01)

    research.PROVIDERS["instagram_hashtag"] = hashtag
    # brand B1's latin alias marks its own accounts
    proj = ok(client.get(f"/v1/projects/{pid}"))
    cfg = proj["config"]
    cfg["brands"][0]["aliases"] = ["Brand1"]
    ok(client.patch(f"/v1/projects/{pid}", json={"base_version": proj["version"], "changes": {"brands": cfg["brands"]}}))
    plan = ok(client.get(f"/v1/projects/{pid}/research-plan"))
    it = item(plan, "influencer")
    ok(client.put(f"/v1/research-items/{it['id']}/inputs", json={"post_urls": [], "hashtags": ["#브랜드1", "brand1"]}))
    job = ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [it["id"]]}), 202)["job"]
    res = ok(client.get(f"/v1/jobs/{job['id']}"))["result"]["items"][it["id"]]
    d = res["discovered"]
    assert d["found"] == 4 and d["official"] == 1 and d["out_of_period"] == 1 and d["added"] == 2
    saved = ok(client.get(f"/v1/projects/{pid}/research-plan"))
    urls = item(saved, "influencer")["inputs"]["post_urls"]
    assert urls == ["https://www.instagram.com/p/AAA/", "https://www.instagram.com/p/BBB/"]  # best engagement first
    assert fakes.calls["instagram_post"] >= 2 and res["posts"] >= 1  # the fake returns one post id for every URL


def test_hashtag_discovery_leaves_out_small_and_foreign_creators(client, fakes, monkeypatch):
    """P2-10: 팔로워 1,000 미만(small)과 캡션·바이오에 한글이 없는 계정(foreign)은 넣지 않고 건수만 남긴다.
    캡션에 한글이 있으면 바이오가 영어여도 한국어 계정으로 본다."""
    from datetime import date, timedelta

    monkeypatch.setenv("APIFY_TOKEN", "test-token")
    monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)
    pid, plan = setup_project(client)
    clear_cache()
    it = item(plan, "influencer")
    day = str(date.fromisoformat(it["period_start"]) + timedelta(days=30))
    post = lambda code, who, caption, likes: {"url": f"https://www.instagram.com/p/{code}/", "posted_at": day,
                                              "creator": who, "likes": likes, "comments": 1, "views": None,
                                              "caption": caption}

    def hashtag(tags, per_tag=60, **kw):
        fakes._hit("instagram_hashtag")
        return CallResult(data={"posts": [post("K1", "seoul_runner", "", 900), post("T1", "tiny_kr", "좋아요", 800),
                                          post("F1", "us_traveler", "love my bag", 700),
                                          post("K2", "kr_caption", "여행 가방 추천", 600)]}, cost_usd=0.01)

    profiles = {"seoul_runner": (52000, "서울 러닝 크루"), "tiny_kr": (300, "일상"), "us_traveler": (90000, "NYC traveler"),
                "kr_caption": (4000, "travel lover")}

    def instagram_profile(handle, **kw):
        fakes._hit("instagram_profile")
        followers, bio = profiles.get(handle, (80000, "서울"))
        return CallResult(data={"followers": followers, "name": handle, "bio": bio}, cost_usd=0.002)

    research.PROVIDERS.update(instagram_hashtag=hashtag, instagram_profile=instagram_profile)
    ok(client.put(f"/v1/research-items/{it['id']}/inputs", json={"post_urls": [], "hashtags": ["#브랜드1"]}))
    job = ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [it["id"]]}), 202)["job"]
    res = ok(client.get(f"/v1/jobs/{job['id']}"))["result"]["items"][it["id"]]
    d = res["discovered"]
    assert d["small"] == 1 and d["foreign"] == 1 and d["added"] == 2
    urls = item(ok(client.get(f"/v1/projects/{pid}/research-plan")), "influencer")["inputs"]["post_urls"]
    assert urls == ["https://www.instagram.com/p/K1/", "https://www.instagram.com/p/K2/"]


def test_creator_filter_thresholds_come_from_rules_config():
    from core.rules.config import RulesConfig
    rules = RulesConfig.load()
    assert rules.creator_min_followers == 1000 and rules.creator_require_korean is True


def test_case_commentary_rewrite_then_accept(client, fakes):
    pid, plan = setup_project(client)
    item_ = next(i for i in plan["items"] if i["section_id"] == "campaign" and i["entity"] == "경쟁X")
    m = ok(client.post(f"/v1/projects/{pid}/materials", json={
        "title": "경쟁X 팝업 캠페인", "url": "https://example.com/campaign/x", "brand_id": "B1", "entity": "경쟁X",
        "section_id": "campaign", "research_item_id": item_["id"]}), 201)
    a = ok(client.post(f"/v1/materials/{m['id']}/assets", files={"file": ("case.png", png(), "image/png")}), 201)
    ok(client.patch(f"/v1/assets/{a['id']}", json={"review_status": "accepted"}))
    c = ok(client.post(f"/v1/materials/{m['id']}/claims", json={"kind": "fact", "text": "협업 캡슐 컬렉션 출시"}), 201)
    ok(client.patch(f"/v1/claims/{c['id']}", json={"base_version": c["version"], "review_status": "accepted"}))
    ok(client.patch(f"/v1/materials/{m['id']}/review", json={"status": "accepted"}))

    job = ok(client.post(f"/v1/projects/{pid}/case-commentary", json={}), 202)["job"]
    job = ok(client.get(f"/v1/jobs/{job['id']}"))
    assert job["state"] == "succeeded" and job["result"]["proposed"] == 1

    props = ok(client.get(f"/v1/projects/{pid}/case-commentary"))
    cc = next(p for p in props if p["material_id"] == m["id"])
    assert cc["status"] == "pending" and cc["attempts"] == 2  # first answer had a digit, the rewrite dropped it
    assert "완판" in cc["detail"] and "3" not in cc["detail"]
    ok(client.post(f"/v1/case-commentary/{cc['id']}/review", json={"action": "accept"}))

    updated = ok(client.get(f"/v1/materials/{m['id']}"))
    assert updated["ai_detail"] == cc["detail"] and updated["ai_implication"] == cc["implication"]
    sp = ok(client.get(f"/v1/projects/{pid}/slide-plan"))
    assert not [i for i in sp["qc"]["issues"] if i["severity"] == "block" and str(i.get("slide_id", "")).startswith("C2")]


def test_owned_item_collects_channel_facts_and_top_posts(client, fakes):
    pid, plan = setup_project(client)
    proj = ok(client.get(f"/v1/projects/{pid}"))
    cfg = proj["config"]
    cfg["brands"][0]["official_profiles"] = [
        {"channel": "instagram", "url": "https://www.instagram.com/brand1/"},
        {"channel": "youtube", "url": "https://www.youtube.com/channel/UCabc/"},
    ]
    cfg["enabled_slides"] = cfg["enabled_slides"] + ["2-1", "2-2", "2-4"]
    ok(client.patch(f"/v1/projects/{pid}", json={"base_version": proj["version"],
                                                 "changes": {"brands": cfg["brands"], "enabled_slides": cfg["enabled_slides"]}}))
    plan = ok(client.get(f"/v1/projects/{pid}/research-plan"))
    it = item(plan, "owned")
    job = ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [it["id"]]}), 202)["job"]
    res = ok(client.get(f"/v1/jobs/{job['id']}"))["result"]["items"][it["id"]]
    assert res["status"] == "succeeded"
    assert fakes.calls["instagram_user_posts"] == 1 and fakes.calls["youtube_channel_videos"] == 1

    posts = ok(client.get(f"/v1/projects/{pid}/owned-posts"))
    assert len(posts) == 3  # 댓글 분석용 게시물은 이미지가 없어도 보관한다
    assert [p["likes"] for p in posts] == [900, 500, 100]  # ordered by likes desc
    # 피드백 #2(자사 SNS 정량 데이터): 조회수도 함께 저장된다(사진 게시물은 플랫폼이 공개 안 해 None).
    assert [p["views"] for p in posts] == [45000, None, None]
    # 피드백 #2(댓글 감성 분석): 댓글 표본을 가져와 긍정/부정/중립으로 분류해 둔다.
    assert fakes.calls["instagram_post_comments"] == 3  # 반응 상위 게시물마다 한 번씩
    assert fakes.calls["comment_sentiment"] == 3
    for p in posts:
        s = p["comment_sentiment"]
        assert s["sample_size"] == 3 and s["positive"] == 1 and s["negative"] == 1 and s["neutral"] == 1
        assert s["pain_points"] == ["품질 불만"]
    for p in posts:
        if p["asset"]:
            assert p["asset"]["review_status"] == "candidate"
            ok(client.patch(f"/v1/assets/{p['asset']['id']}", json={"review_status": "accepted"}))

    facts = ok(client.get(f"/v1/projects/{pid}/facts"))
    owned_facts = [f for f in facts if f["metric"].startswith("owned_")]
    assert owned_facts  # followers, posts_monthly, likes_median, posts_by_month…
    for f in owned_facts:
        ok(client.patch(f"/v1/facts/{f['id']}/review", params={"project_id": pid}, json={"action": "confirm"}))

    sp = ok(client.get(f"/v1/projects/{pid}/slide-plan"))
    assert next(s for s in sp["plan"] if s["slot_id"] == "2-1")["readiness"] == "ready"
    assert next(s for s in sp["plan"] if s["slot_id"] == "2-4")["readiness"] == "ready"
    blocking = [i for i in sp["qc"]["issues"] if i["severity"] == "block" and i.get("block_id") in ("2-1", "2-2", "2-4")]
    assert blocking == [], blocking

    # rerun without force: the succeeded item is skipped, no duplicate OwnedPost rows
    job2 = ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [it["id"]]}), 202)["job"]
    assert ok(client.get(f"/v1/jobs/{job2['id']}"))["result"]["items"][it["id"]]["status"] == "skipped"
    assert len(ok(client.get(f"/v1/projects/{pid}/owned-posts"))) == 3


def test_owned_item_collects_every_channel_and_every_account(client, fakes):
    """P2-6: 틱톡·페이스북·X·스레드·유튜브 쇼츠·네이버 블로그 + 한 채널의 계정 여러 개(account dim).
    비공개 계정은 '접근 불가'로 남고 다른 채널은 계속 모은다. X는 인기 글이라 게시 빈도를 만들지 않는다."""
    clear_cache()
    pid, plan = setup_project(client)
    proj = ok(client.get(f"/v1/projects/{pid}"))
    cfg = proj["config"]
    cfg["brands"][0]["official_profiles"] = [
        {"channel": "instagram", "url": "https://www.instagram.com/brand1/"},
        {"channel": "instagram", "url": "https://www.instagram.com/brand1_outlet/"},
        {"channel": "youtube", "url": "https://www.youtube.com/@brand1"},
        {"channel": "tiktok", "url": "https://www.tiktok.com/@brand1"},
        {"channel": "facebook", "url": "https://www.facebook.com/brand1"},
        {"channel": "x", "url": "https://x.com/brand1"},
        {"channel": "threads", "url": "https://www.threads.net/@brand1"},
        {"channel": "threads", "url": "https://www.threads.net/@brand1_private"},
        {"channel": "blog", "url": "https://blog.naver.com/brand1blog"},
    ]
    ok(client.patch(f"/v1/projects/{pid}", json={"base_version": proj["version"], "changes": {"brands": cfg["brands"]}}))
    it = item(ok(client.get(f"/v1/projects/{pid}/research-plan")), "owned")
    start, end = it["period_start"], it["period_end"]
    assert start <= "2026-03-01" and end >= "2026-09-30"

    def instagram_user_posts(handle, next_max_id=None, **kw):
        fakes._hit("instagram_user_posts")
        return CallResult(data={"posts": [{"post_id": f"{handle}-1", "posted_at": "2026-05-05", "likes": 10, "comments": 1,
                                           "views": None, "url": None, "image_url": None}],
                                "next_max_id": None, "more_available": False}, cost_usd=0.002)

    def tiktok_profile(handle, **kw):
        fakes._hit("tiktok_profile")
        return CallResult(data={"followers": 5000, "videos": 40, "name": handle}, usage={"credits": 1}, cost_usd=0.002)

    def tiktok_profile_videos(handle, max_cursor=None, **kw):
        fakes._hit("tiktok_profile_videos")
        old = {"post_id": "t0", "posted_at": "2025-06-01", "views": 1, "likes": 1, "comments": 0, "shares": 0, "pinned": True}
        if max_cursor is None:  # 1쪽: 고정된 옛 글 + 최신 글 2개 — 고정 글 때문에 멈추면 안 된다
            return CallResult(data={"posts": [old,
                                              {"post_id": "t1", "posted_at": "2026-09-01", "views": 1000, "likes": 100,
                                               "comments": 10, "shares": 4, "pinned": False},
                                              {"post_id": "t2", "posted_at": "2026-08-01", "views": 3000, "likes": 300,
                                               "comments": 30, "shares": 8, "pinned": False}],
                                    "cursor": "c2", "has_more": True}, cost_usd=0.002)
        return CallResult(data={"posts": [{"post_id": "t3", "posted_at": "2026-03-01", "views": 2000, "likes": 200,
                                           "comments": 20, "shares": 6, "pinned": False},
                                          {"post_id": "t4", "posted_at": "2025-12-01", "views": 9, "likes": 9, "comments": 9,
                                           "shares": 9, "pinned": False}], "cursor": "c3", "has_more": True}, cost_usd=0.002)

    def facebook_profile(url, **kw):
        fakes._hit("facebook_profile")
        return CallResult(data={"followers": 12000, "name": "브랜드A"}, cost_usd=0.002)

    def facebook_profile_posts(url, cursor=None, **kw):
        fakes._hit("facebook_profile_posts")
        return CallResult(data={"posts": [{"post_id": "f1", "url": "u", "posted_at": "2026-07-01", "likes": 50, "comments": 5,
                                           "shares": 2, "views": None}], "cursor": None}, cost_usd=0.002)

    def twitter_profile(handle, **kw):
        fakes._hit("twitter_profile")
        return CallResult(data={"followers": 800, "name": handle}, cost_usd=0.002)

    def twitter_user_tweets(handle, **kw):
        fakes._hit("twitter_user_tweets")
        return CallResult(data={"posts": [{"post_id": "x1", "url": "u", "posted_at": "2026-04-01", "likes": 30, "comments": 3,
                                           "shares": 6, "views": 900},
                                          {"post_id": "x0", "url": "u", "posted_at": "2023-01-01", "likes": 999,
                                           "comments": 99, "shares": 99, "views": 99999}]}, cost_usd=0.002)

    def threads_profile(handle, **kw):
        fakes._hit("threads_profile")
        if handle.endswith("private"):
            raise ProviderError("SOURCE_UNAVAILABLE", "Threads 비공개 계정이라 볼 수 없습니다", None)
        return CallResult(data={"followers": 300, "name": handle}, cost_usd=0.002)

    def threads_user_posts(handle, **kw):
        fakes._hit("threads_user_posts")
        return CallResult(data={"posts": [{"post_id": "h1", "url": "u", "posted_at": "2026-06-01", "likes": 7, "comments": 1,
                                           "shares": 0}]}, cost_usd=0.002)  # 기간 시작까지 닿지 못한 묶음

    def youtube_channel_shorts(channel_id=None, handle=None, continuation_token=None, **kw):
        fakes._hit("youtube_channel_shorts")
        shorts = [{"id": f"s{i}", "url": f"https://youtube.com/watch?v=s{i}", "title": "s", "views": 100 * (i + 1),
                   "likes": 1, "comments": 0, "published_at": f"2026-0{i + 1}-15"} for i in range(3)]
        return CallResult(data={"shorts": shorts, "continuation_token": None}, cost_usd=0.002)

    fakes.naver_items = {"blog": [
        {"title": "공식 글", "url": "https://blog.naver.com/brand1blog/1", "snippet": "", "date": "2026-02-01",
         "author": "브랜드A 공식", "author_url": "https://blog.naver.com/brand1blog"},
        {"title": "다른 사람 글", "url": "https://blog.naver.com/someone/2", "snippet": "", "date": "2026-02-02",
         "author": "x", "author_url": "https://blog.naver.com/someone"}]}
    for name, fn in dict(instagram_user_posts=instagram_user_posts, tiktok_profile=tiktok_profile,
                         tiktok_profile_videos=tiktok_profile_videos, facebook_profile=facebook_profile,
                         facebook_profile_posts=facebook_profile_posts, twitter_profile=twitter_profile,
                         twitter_user_tweets=twitter_user_tweets, threads_profile=threads_profile,
                         threads_user_posts=threads_user_posts, youtube_channel_shorts=youtube_channel_shorts).items():
        research.PROVIDERS[name] = fn

    job = ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [it["id"]]}), 202)["job"]
    res = ok(client.get(f"/v1/jobs/{job['id']}"))["result"]["items"][it["id"]]
    assert res["status"] == "partial"  # 비공개 스레드 계정 하나 때문에
    assert any(e["code"] == "ACCESS_UNAVAILABLE" and "비공개" in e["message"] for e in res["errors"])
    assert {c["channel"] for c in res["channels"]} == {"instagram", "youtube", "tiktok", "facebook", "x", "threads", "naver_blog"}
    assert fakes.calls["tiktok_profile_videos"] == 2  # 고정된 옛 글에서 멈추지 않고 다음 쪽까지

    facts = [f for f in ok(client.get(f"/v1/projects/{pid}/facts")) if f["metric"].startswith("owned_")]

    def one(metric, channel, **dims):
        hits = [f for f in facts if f["metric"] == metric and f["dims"].get("channel") == channel
                and all(f["dims"].get(k) == v for k, v in dims.items())]
        assert len(hits) == 1, (metric, channel, dims, hits)
        return float(hits[0]["value"])

    # 인스타그램 계정 두 개는 account dim으로 나뉜다
    assert one("owned_followers", "instagram", account="brand1") == one("owned_followers", "instagram", account="brand1_outlet")
    months = len({f["dims"]["month"] for f in facts if f["metric"] == "owned_posts_by_month" and f["dims"]["channel"] == "tiktok"})
    assert one("owned_followers", "tiktok") == 5000
    assert one("owned_posts_monthly", "tiktok") == round(3 / months, 2)  # t1·t2·t3 (고정 글·기간 밖 제외)
    assert one("owned_likes_median", "tiktok") == 200 and one("owned_shares_median", "tiktok") == 6
    assert one("owned_comments_median", "tiktok") == 20 and one("owned_views_avg", "tiktok") == 2000
    assert one("owned_followers", "facebook") == 12000 and one("owned_likes_median", "facebook") == 50
    # X: 팔로워와 인기 게시물 기준 반응만, 게시 빈도 없음
    assert one("owned_followers", "x") == 800 and one("owned_likes_median", "x", basis="popular") == 30
    assert not [f for f in facts if f["dims"].get("channel") == "x" and "posts" in f["metric"]]
    # 스레드: 최근 묶음이 기간 시작까지 닿지 못해 월 게시 수는 만들지 않는다
    assert one("owned_followers", "threads", account="brand1") == 300
    assert not [f for f in facts if f["dims"].get("channel") == "threads" and "posts" in f["metric"]]
    assert any("Threads" in n for n in res["notes"])
    # 유튜브 쇼츠는 쇼츠 탭에서
    assert one("owned_videos_monthly", "youtube", format="shorts") == round(3 / months, 2)
    assert one("owned_views_avg", "youtube", format="shorts") == 200
    # 네이버 블로그: 공식 블로그 글만
    assert one("owned_posts_monthly", "naver_blog") == round(1 / months, 2)
    assert all(f["verification_status"] == "candidate" for f in facts)


def test_owned_item_also_runs_for_a_competitor_without_leaking_into_self(client, fakes):
    clear_cache()
    pid, plan = setup_project(client)
    proj = ok(client.get(f"/v1/projects/{pid}"))
    cfg = proj["config"]
    cfg["brands"][0]["official_profiles"] = [{"channel": "instagram", "url": "https://www.instagram.com/brand1/"}]
    cfg["brands"][0]["competitor_profiles"] = {
        "경쟁X": [{"channel": "instagram", "url": "https://www.instagram.com/competitorx/"}]}
    cfg["enabled_slides"] = cfg["enabled_slides"] + ["2-1"]
    ok(client.patch(f"/v1/projects/{pid}", json={"base_version": proj["version"],
                                                 "changes": {"brands": cfg["brands"], "enabled_slides": cfg["enabled_slides"]}}))
    plan = ok(client.get(f"/v1/projects/{pid}/research-plan"))
    self_item, comp_item = item(plan, "owned", "브랜드A"), item(plan, "owned", "경쟁X")
    assert self_item["required"] is True and comp_item["required"] is False  # 경쟁사는 선택

    # Real Instagram post ids are globally unique per account; the shared fake must vary them by
    # handle too, or the self/competitor runs collide on owned_posts' (project, channel, post_id).
    def instagram_user_posts(handle, next_max_id=None, **kw):
        fakes._hit("instagram_user_posts")
        if next_max_id:
            return CallResult(data={"posts": [], "next_max_id": None, "more_available": False}, cost_usd=0.002)
        posts = [{"post_id": f"{handle}-p1", "posted_at": "2026-08-05", "likes": 500, "comments": 10, "views": None,
                 "url": f"https://instagram.com/p/{handle}-p1/", "image_url": "https://img.example.com/p1.jpg"}]
        return CallResult(data={"posts": posts, "next_max_id": None, "more_available": False}, cost_usd=0.002)

    research.PROVIDERS["instagram_user_posts"] = instagram_user_posts

    job = ok(client.post(f"/v1/projects/{pid}/research-runs",
                         json={"item_ids": [self_item["id"], comp_item["id"]]}), 202)["job"]
    res = ok(client.get(f"/v1/jobs/{job['id']}"))["result"]["items"]
    assert res[self_item["id"]]["status"] == "succeeded" and res[comp_item["id"]]["status"] == "succeeded"

    facts = ok(client.get(f"/v1/projects/{pid}/facts"))
    by_entity = {}
    for f in facts:
        if f["metric"] == "owned_followers" and f["dims"].get("channel") == "instagram":
            by_entity[f["entity"]] = f
    assert set(by_entity) == {"브랜드A", "경쟁X"}  # both collected, kept apart by entity

    posts = ok(client.get(f"/v1/projects/{pid}/owned-posts"))
    assert {p["entity"] for p in posts} == {"브랜드A", "경쟁X"}

    # 2-1 is self-only: confirming every owned fact must never pull 경쟁X's numbers onto 브랜드A's slide.
    for f in facts:
        if f["metric"].startswith("owned_"):
            ok(client.patch(f"/v1/facts/{f['id']}/review", params={"project_id": pid}, json={"action": "confirm"}))
    sp = ok(client.get(f"/v1/projects/{pid}/slide-plan"))
    inventory = next(s for s in sp["plan"] if s["slot_id"] == "2-1")
    assert inventory["readiness"] == "thin"  # 경쟁사 Instagram 수치가 자사의 두 번째 채널로 새지 않는다
    build_job = ok(client.post(f"/v1/projects/{pid}/deck-builds"), 202)["job"]
    ok(client.get(f"/v1/jobs/{build_job['id']}"))
    deck = ok(client.get(f"/v1/projects/{pid}/decks"))[0]
    spec = ok(client.get(f"/v1/decks/{deck['id']}"))["spec"]
    assert not any(s["slide_id"] == "2-1" for s in spec["slides"])
    compare = next(s for s in spec["slides"] if s["slide_id"] == "OW-CMP")
    assert {b["entity"] for b in compare["bindings"]} >= {"브랜드A", "경쟁X"}


def test_collection_mix_flags_press_heavy_research_and_thin_channels(client, fakes):
    pid, plan = setup_project(client)
    proj = ok(client.get(f"/v1/projects/{pid}"))
    with SessionLocal() as db:
        # 3 press materials (언론) — two of them duplicates of the same activity, so only 2 count.
        srcs = [Source(id=new_id("SRC"), project_id=pid, title=f"기사{i}", source_type="web") for i in range(3)]
        db.add_all(srcs)
        db.flush()
        mats = [Material(id=new_id("EV"), project_id=pid, source_id=srcs[i].id, brand_id="B1", entity="브랜드A",
                         section_id="campaign", title=f"기사{i}", review_status="candidate") for i in range(3)]
        mats[2].duplicate_of = mats[0].id  # 같은 활동을 다룬 기사 묶음은 1건
        db.add_all(mats)
        # an unavailable (access-walled) source under the same brand
        walled_src = Source(id=new_id("SRC"), project_id=pid, title="로그인 필요", source_type="web", access_status="unavailable")
        db.add(walled_src)
        db.flush()
        db.add(Material(id=new_id("EV"), project_id=pid, source_id=walled_src.id, brand_id="B1", entity="브랜드A",
                        section_id="campaign", title="로그인 필요", review_status="excluded"))
        # 4 influencer posts (below the 10 minimum)
        for i in range(4):
            db.add(PostRow(project_id=pid, batch_id="BATCH-x", post_id=f"p{i}",
                           data={"brand_id": "B1", "owner_type": "creator"}))
        db.commit()

    r = ok(client.get(f"/v1/projects/{pid}/collection-mix"))
    row = next(b for b in r["brands"] if b["brand_id"] == "B1")
    assert row["channels"]["press"]["count"] == 2  # duplicate collapsed, excluded one not counted
    assert row["channels"]["influencer"] == {"count": 4, "min": 10, "enough": False,
                                             "label": "SNS·인플루언서", "action": "조사 계획에서 인플루언서 항목을 다시 모으세요"}
    assert row["channels"]["owned"]["enough"] is False and row["channels"]["owned"]["total"] == 0  # 공식 계정 미등록
    assert row["channels"]["review"] == {"count": 0, "label": "리뷰", "enough": False, "min": 30, "platforms": 0,
                                         "platforms_min": 2, "action": "조사 계획에서 커머스 리뷰 항목을 다시 모으세요"}
    assert row["channels"]["cafe_blog"]["count"] == 0 and row["channels"]["cafe_blog"]["enough"] is False
    assert row["channels"]["community"]["count"] == 0 and row["channels"]["community"]["sites"] == 0
    assert row["access_unavailable"] == 1
    # press(2) / total(2 press + 4 influencer) = 1/3 ≈ 0.333 — not over 40% yet with this mix
    assert row["press_ratio"] == round(2 / 6, 3)


def test_collection_mix_flags_review_required_industry_filled_with_community_only(client, fakes):
    """Phase 2 §5: 리뷰 필수 업종(전자·뷰티·패션)인데 소비자 원문이 커뮤니티뿐이면 '수집 부족'으로 본다."""
    from app.models import ReviewSnapshot

    p = ok(client.post("/v1/projects", json={
        "name": "리뷰 비중 테스트", "client": "고객", "period": {"start": "2026-01-01", "end": "2026-09-30"},
        "brands": [{"id": "B1", "name": "브랜드A", "competitors": ["경쟁X"], "industry": "패션"}]}), 201)
    pid = p["id"]
    with SessionLocal() as db:
        def voc(i, url):
            src = Source(id=new_id("SRC"), project_id=pid, title=f"글{i}", original_url=url, source_type="web")
            db.add(src)
            db.flush()
            db.add(Material(id=new_id("EV"), project_id=pid, source_id=src.id, brand_id="B1", entity="브랜드A",
                            section_id="voc", title=f"글{i}", review_status="candidate"))
        for i in range(25):
            voc(i, f"https://cafe.naver.com/x/{i}")
        db.commit()

    r = ok(client.get(f"/v1/projects/{pid}/collection-mix"))
    row = next(b for b in r["brands"] if b["brand_id"] == "B1")
    assert row["channels"]["review"]["count"] == 0
    assert row["review_share"] == 0.0
    assert row["review_share_warning"] is True  # 커뮤니티만 25건 — 리뷰 비중 0%, 필수 업종인데 부족

    with SessionLocal() as db:
        db.add(ReviewSnapshot(id=new_id("REV"), project_id=pid, brand_id="B1", entity="브랜드A", role="self",
                              platform="musinsa", product_name="상품", product_url="https://musinsa.com/products/1",
                              access_status="ok", rating=4.5, rating_scale=5.0, review_count=120,
                              measured_at=date(2026, 9, 1), review_status="candidate"))
        db.add(ReviewSnapshot(id=new_id("REV"), project_id=pid, brand_id="B1", entity="브랜드A", role="self",
                              platform="29cm", product_name="상품", product_url="https://29cm.co.kr/products/1",
                              access_status="ok", rating=4.2, rating_scale=5.0, review_count=80,
                              measured_at=date(2026, 9, 1), review_status="candidate"))
        db.commit()

    r2 = ok(client.get(f"/v1/projects/{pid}/collection-mix"))
    row2 = next(b for b in r2["brands"] if b["brand_id"] == "B1")
    assert row2["channels"]["review"]["count"] == 200 and row2["channels"]["review"]["platforms"] == 2
    assert row2["channels"]["review"]["enough"] is True  # 30건 이상, 2개 플랫폼 이상
    assert row2["review_share"] == round(200 / 225, 3)
    assert row2["review_share_warning"] is False  # 이제 리뷰 비중이 50% 넘음


def test_collection_mix_community_needs_posts_spread_across_three_sites(client, fakes):
    pid, plan = setup_project(client)
    with SessionLocal() as db:
        def voc(i, url):
            src = Source(id=new_id("SRC"), project_id=pid, title=f"글{i}", original_url=url, source_type="web")
            db.add(src)
            db.flush()
            db.add(Material(id=new_id("EV"), project_id=pid, source_id=src.id, brand_id="B1", entity="브랜드A",
                            section_id="voc", title=f"글{i}", review_status="candidate"))
        # 2 cafe_blog posts (same site) + 2 community posts split across only 2 sites — short of 3.
        voc(1, "https://blog.naver.com/a/1")
        voc(2, "https://blog.naver.com/a/2")
        voc(3, "https://gall.dcinside.com/b/1")
        voc(4, "https://www.fmkorea.com/c/1")
        db.commit()

    r = ok(client.get(f"/v1/projects/{pid}/collection-mix"))
    row = next(b for b in r["brands"] if b["brand_id"] == "B1")
    assert row["channels"]["cafe_blog"]["count"] == 2 and row["channels"]["cafe_blog"]["enough"] is False  # 20건 미만
    assert row["channels"]["community"]["count"] == 2 and row["channels"]["community"]["sites"] == 2
    assert row["channels"]["community"]["enough"] is False  # 20건도, 3곳도 안 됨


def test_collection_mix_owned_channel_enough_once_every_confirmed_account_is_recent(client, fakes):
    pid, plan = setup_project(client)
    proj = ok(client.get(f"/v1/projects/{pid}"))
    cfg = proj["config"]
    cfg["brands"][0]["official_profiles"] = [{"channel": "instagram", "url": "https://www.instagram.com/brand1/"}]
    ok(client.patch(f"/v1/projects/{pid}", json={"base_version": proj["version"], "changes": {"brands": cfg["brands"]}}))
    plan = ok(client.get(f"/v1/projects/{pid}/research-plan"))
    it = item(plan, "owned", "브랜드A")
    job = ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [it["id"]]}), 202)["job"]
    assert ok(client.get(f"/v1/jobs/{job['id']}"))["result"]["items"][it["id"]]["status"] == "succeeded"

    r = ok(client.get(f"/v1/projects/{pid}/collection-mix"))
    row = next(b for b in r["brands"] if b["brand_id"] == "B1")
    assert row["channels"]["owned"] == {"count": 1, "total": 1, "enough": True, "label": "공식 채널",
                                        "action": "자료 확인에서 '다시 모으기'로 최근 자료를 받으세요"}


def test_voc_item_finds_naver_blog_and_kin_posts_via_search_api(client, fakes):
    """P2-3: 블로그·지식iN은 네이버 검색 API로, 카페글이 비활성이면 카페는 Perplexity로."""
    pid, plan = setup_project(client)
    clear_cache()
    it = item(plan, "voc", "브랜드A")
    fakes.naver_items = {
        "blog": [{"title": "브랜드A 3개월 사용 후기", "url": "https://blog.naver.com/a/1", "snippet": "튼튼해요",
                  "date": "2026-05-01", "author": "여행 블로그", "author_url": "https://blog.naver.com/a"},
                 {"title": "브랜드A 언박싱", "url": "https://blog.naver.com/b/2", "snippet": "예뻐요",
                  "date": "2026-06-02", "author": "일상 블로그", "author_url": "https://blog.naver.com/b"},
                 {"title": "브랜드A 오래된 후기", "url": "https://blog.naver.com/c/3", "snippet": "",
                  "date": "2019-01-01", "author": "x", "author_url": None}],
        "kin": [{"title": "브랜드A 바퀴 고장 났어요", "url": "https://kin.naver.com/qna/1", "snippet": "AS 되나요",
                 "date": None, "author": None, "author_url": None}],
    }
    fakes.naver_denied = {"cafearticle"}
    seen_sites = []

    def search(queries, sites=None, **kw):
        fakes._hit("search")
        seen_sites.append(list(sites or []))
        return CallResult(data={"id": "s", "results": []}, cost_usd=0.005)
    research.PROVIDERS["search"] = search
    job = ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [it["id"]]}), 202)["job"]
    res = ok(client.get(f"/v1/jobs/{job['id']}"))["result"]["items"][it["id"]]
    assert res["naver_search"]["blog"] == 2 and res["naver_search"]["kin"] == 1
    assert "활성화" in res["naver_search"]["cafearticle"]  # 비활성 사유가 남는다
    assert "blog.naver.com" not in seen_sites[0] and "cafe.naver.com" in seen_sites[0]  # 카페는 Perplexity가
    mats = [m for m in ok(client.get(f"/v1/projects/{pid}/materials")) if m["section_id"] == "voc"]
    urls = {m["source"]["url"] for m in mats}
    assert urls == {"https://blog.naver.com/a/1", "https://blog.naver.com/b/2", "https://kin.naver.com/qna/1"}
    assert all(m["review_status"] == "candidate" for m in mats)  # 자동 채택하지 않는다
    assert res["out_of_period"] >= 1  # 2019년 글은 기간 밖이라 빠진다


def test_voc_item_collects_and_classifies_consumer_posts(client, fakes):
    pid, plan = setup_project(client)
    clear_cache()
    it = item(plan, "voc", "브랜드A")
    # 네이버 검색 API가 막히면(비활성) Perplexity 사이트 검색이 블로그·카페까지 예전처럼 찾는다.
    fakes.naver_denied = {"blog", "cafearticle", "kin"}

    def search(queries, sites=None, **kw):
        fakes._hit("search")
        assert sites and "blog.naver.com" in sites and "dcinside.com" in sites
        return CallResult(data={"id": "s", "results": [
            {"title": "브랜드A 후기", "url": "https://blog.naver.com/x/1", "snippet": "좋아요", "date": "2026-05-01"},
            {"title": "브랜드A 솔직 후기", "url": "https://gall.dcinside.com/board/view/?id=x&no=1", "snippet": "별로", "date": "2026-05-02"},
            {"title": "브랜드A 카페 글", "url": "https://cafe.naver.com/x/2", "snippet": "", "date": "2026-05-03"},
        ]}, cost_usd=0.005)

    def fetch_page(url, **kw):
        fakes._hit("fetch_page")
        if "cafe.naver.com" in url:
            return Page(url=url, final_url="https://nid.naver.com/nidlogin.login?url=" + url, title="네이버 로그인",
                       text="로그인 후 이용해주세요", content_hash="hlogin", published=None, publisher=None, image_urls=[])
        if "dcinside" in url:
            return Page(url=url, final_url=url, title="디시 글", text="협찬 받아서 써봤는데 디자인이 별로였어요 #협찬",
                       content_hash="h2", published="2026-05-02", publisher="dcinside", image_urls=[])
        return Page(url=url, final_url=url, title="네이버 블로그 글", text="가격도 괜찮고 품질도 좋아서 친구 추천으로 알게 됐어요",
                   content_hash="h1", published="2026-05-01", publisher="네이버 블로그", image_urls=[])

    def structured(system, user, schema, **kw):
        if set(schema["properties"]) == {
            "relevant", "headline", "sentiment", "topic", "awareness", "sponsored", "pain_points",
        }:
            fakes._hit("voc_classify")
            if "협찬" in user:
                return CallResult(data={"relevant": True, "headline": "디자인이 별로였음", "sentiment": "negative",
                                        "topic": "design", "awareness": "other", "sponsored": True,
                                        "pain_points": ["디자인 불만"]}, cost_usd=0.001)
            return CallResult(data={"relevant": True, "headline": "가격이 합리적", "sentiment": "positive",
                                    "topic": "price", "awareness": "referral", "sponsored": False,
                                    "pain_points": []}, cost_usd=0.001)
        return fakes.structured(system, user, schema, **kw)

    research.PROVIDERS["search"] = search
    research.PROVIDERS["fetch_page"] = fetch_page
    research.PROVIDERS["structured"] = structured

    job = ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [it["id"]]}), 202)["job"]
    res = ok(client.get(f"/v1/jobs/{job['id']}"))["result"]["items"][it["id"]]
    assert res["created"] == 3 and res["access_unavailable"] == 1
    assert res["channels"] == {"cafe_blog": 1, "community": 1}
    assert fakes.calls["voc_classify"] == 2  # the login-walled card never reaches AI classification

    mats = {m["source"]["url"]: m for m in ok(client.get(f"/v1/projects/{pid}/materials")) if m["section_id"] == "voc"}
    blog = mats["https://blog.naver.com/x/1"]
    assert blog["voc_sentiment"] == "positive" and blog["voc_topic"] == "price" and blog["voc_awareness"] == "referral"
    assert blog["voc_sponsored"] is False
    dc = mats["https://gall.dcinside.com/board/view/?id=x&no=1"]
    assert dc["voc_sponsored"] is True
    walled = mats["https://cafe.naver.com/x/2"]
    assert walled["source"]["access_status"] == "unavailable"

    # 묶음 채택: 접근 불가·협찬 표기 카드는 사람의 확인을 기다리고, 나머지만 한 번에 채택된다.
    out = ok(client.post(f"/v1/projects/{pid}/materials/accept-all"))
    assert out["accepted"] == 1 and out["left"] == 2


def test_voc_item_also_collects_x_and_threads_public_posts(client, fakes):
    """피드백 #5(SNS 네이티브 검색): 검색 결과 자체에 본문이 있어 별도 페이지 수집 없이 바로 쓴다."""
    pid, plan = setup_project(client)
    clear_cache()
    it = item(plan, "voc", "브랜드A")

    def search(queries, sites=None, **kw):
        fakes._hit("search")
        return CallResult(data={"id": "s", "results": []}, cost_usd=0.005)  # 카페·블로그는 이번엔 비움

    def twitter_search_posts(query, **kw):
        fakes._hit("twitter_search_posts")
        return CallResult(data={"posts": [
            {"url": "https://x.com/foo/status/1", "text": "브랜드A 가성비 좋아서 추천함", "posted_at": "2026-05-01",
             "author": "foo", "likes": 10},
        ], "cursor": None}, cost_usd=0.002)

    def threads_search(query, **kw):
        fakes._hit("threads_search")
        return CallResult(data={"posts": [
            {"url": "https://www.threads.com/@bar/post/abc", "text": "브랜드A 배송이 너무 느려요", "posted_at": "2026-05-03",
             "author": "bar", "likes": 1},
        ]}, cost_usd=0.002)

    def structured(system, user, schema, **kw):
        if set(schema["properties"]) == {
            "relevant", "headline", "sentiment", "topic", "awareness", "sponsored", "pain_points",
        }:
            fakes._hit("voc_classify")
            if "느려요" in user:
                return CallResult(data={"relevant": True, "headline": "배송 지연", "sentiment": "negative",
                                        "topic": "shipping", "awareness": "other", "sponsored": False,
                                        "pain_points": ["배송 지연"]}, cost_usd=0.001)
            return CallResult(data={"relevant": True, "headline": "가성비 호평", "sentiment": "positive",
                                    "topic": "price", "awareness": "other", "sponsored": False,
                                    "pain_points": []}, cost_usd=0.001)
        return fakes.structured(system, user, schema, **kw)

    research.PROVIDERS["search"] = search
    research.PROVIDERS["twitter_search_posts"] = twitter_search_posts
    research.PROVIDERS["threads_search"] = threads_search
    research.PROVIDERS["structured"] = structured

    job = ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [it["id"]]}), 202)["job"]
    res = ok(client.get(f"/v1/jobs/{job['id']}"))["result"]["items"][it["id"]]
    assert res["created"] == 2 and res["channels"] == {"x_search": 1, "threads_search": 1}
    assert fakes.calls["twitter_search_posts"] == 1 and fakes.calls["threads_search"] == 1

    mats = {m["source"]["url"]: m for m in ok(client.get(f"/v1/projects/{pid}/materials")) if m["section_id"] == "voc"}
    tw = mats["https://x.com/foo/status/1"]
    assert tw["voc_sentiment"] == "positive" and tw["source"]["source_type"] == "social"
    th = mats["https://www.threads.com/@bar/post/abc"]
    assert th["voc_sentiment"] == "negative" and th["voc_topic"] == "shipping"


def test_voc_item_adds_tiktok_youtube_comments_and_kin_as_their_own_channels(client, fakes):
    """P2-8: 틱톡 검색(한국어로 브랜드를 말하는 것만), 유튜브 검색(기간 안 영상의 제목 + 댓글), 지식iN이
    각자 채널로 모이고 수집 현황 화면의 채널별 건수에 보인다. 모두 후보로만 남는다."""
    pid, plan = setup_project(client)
    clear_cache()
    it = item(plan, "voc", "브랜드A")
    assert {"tiktok_search", "youtube_search", "naver_kin"} <= {c["id"] for c in it["channels"]}  # 기본으로 켜진다
    fakes.naver_items = {"kin": [{"title": "브랜드A 바퀴 고장 났어요", "url": "https://kin.naver.com/qna/1",
                                  "snippet": "AS 되나요", "date": "2026-05-01", "author": None, "author_url": None}]}

    def search(queries, sites=None, **kw):
        fakes._hit("search")
        return CallResult(data={"id": "s", "results": []}, cost_usd=0.005)

    def tiktok_search_keyword(query, region=None, **kw):
        fakes._hit("tiktok_search_keyword")
        assert region == "KR"
        return CallResult(data={"posts": [
            {"url": "https://www.tiktok.com/@a/video/1", "text": "브랜드A 캐리어 3개월 써본 후기", "posted_at": "2026-05-01",
             "author": "a", "followers": 5000, "views": 100, "likes": 5, "comments": 1, "region": "KR", "sponsored": False},
            {"url": "https://www.tiktok.com/@b/video/2", "text": "my new 브랜드A luggage", "posted_at": "2026-05-01",
             "author": "b"},  # 한글이 있지만 브랜드 이름만 — 통과
            {"url": "https://www.tiktok.com/@c/video/3", "text": "so light and pretty #luggage", "posted_at": "2026-05-01",
             "author": "c"},  # 해외 영상
            {"url": "https://www.tiktok.com/@d/video/4", "text": "오늘의 여행 짐 싸기", "posted_at": "2026-05-01",
             "author": "d"},  # 브랜드 이야기가 아님
        ], "cursor": None, "has_more": False}, cost_usd=0.002)

    def youtube_search(query, **kw):
        fakes._hit("youtube_search")
        return CallResult(data={"videos": [
            {"url": "https://www.youtube.com/watch?v=v1", "title": "브랜드A 캐리어 리뷰", "posted_at": "2026-06-01",
             "author": "리뷰채널", "views": 9000, "is_short": False},
            {"url": "https://www.youtube.com/watch?v=s1", "title": "브랜드A 쇼츠", "posted_at": None,
             "author": "숏폼", "views": 99999, "is_short": True},  # 게시일을 알 수 없어 뺀다
            {"url": "https://www.youtube.com/watch?v=old", "title": "브랜드A 옛날 리뷰", "posted_at": "2019-01-01",
             "author": "x", "views": 50000, "is_short": False},  # 기간 밖 — 댓글도 부르지 않는다
        ]}, cost_usd=0.002)

    research.PROVIDERS.update(search=search, tiktok_search_keyword=tiktok_search_keyword, youtube_search=youtube_search)
    job = ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [it["id"]]}), 202)["job"]
    res = ok(client.get(f"/v1/jobs/{job['id']}"))["result"]["items"][it["id"]]
    assert res["channels"] == {"kin": 1, "tiktok_search": 2, "youtube_search": 1}
    assert res["skipped"] == {"foreign": 1, "unrelated": 1}
    assert fakes.calls["youtube_video_comments"] == 1  # 기간 안 영상 하나만

    mats = {m["source"]["url"]: m for m in ok(client.get(f"/v1/projects/{pid}/materials")) if m["section_id"] == "voc"}
    yt = mats["https://www.youtube.com/watch?v=v1"]
    assert yt["title"] == "브랜드A 캐리어 리뷰" and "진짜 예뻐요 재구매각" in yt["excerpt"]
    assert yt["source"]["source_type"] == "social"
    assert all(m["review_status"] == "candidate" for m in mats.values())

    mix = ok(client.get(f"/v1/projects/{pid}/collection-mix"))
    row = next(b for b in mix["brands"] if b["brand_id"] == "B1")
    assert row["channels"]["kin"] == {"count": 1, "label": "지식iN"}
    assert row["channels"]["sns_search"] == {"count": 3, "label": "SNS 검색"}


def test_voc_item_skips_new_channels_the_plan_left_out(client, fakes):
    """고르지 않은 채널(틱톡·유튜브·지식iN)은 부르지 않는다. P2-8 이전 계획은 지식iN을 계속 찾는다."""
    pid, plan = setup_project(client)
    clear_cache()
    it = item(plan, "voc", "브랜드A")
    with SessionLocal() as db:
        row = db.get(ResearchItem, it["id"])
        row.channels = ["community", "naver_blog", "x_search", "threads_search"]  # P2-8 이전에 만든 계획
        db.commit()
    research.PROVIDERS["search"] = lambda queries, **kw: CallResult(data={"id": "s", "results": []}, cost_usd=0.005)
    seen_kinds = []
    naver = research.PROVIDERS["naver_search"]
    research.PROVIDERS["naver_search"] = lambda kind, q, **kw: (seen_kinds.append(kind), naver(kind, q, **kw))[1]
    ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [it["id"]]}), 202)
    assert "tiktok_search_keyword" not in fakes.calls and "youtube_search" not in fakes.calls
    assert "kin" in seen_kinds


def _set_competitor_alias(client, pid, entity, alias):
    proj = ok(client.get(f"/v1/projects/{pid}"))
    brands = proj["config"]["brands"]
    brands[0]["entity_aliases"] = {**(brands[0].get("entity_aliases") or {}), entity: [alias]}
    ok(client.patch(f"/v1/projects/{pid}", json={"base_version": proj["version"], "changes": {"brands": brands}}))
    return ok(client.get(f"/v1/projects/{pid}/research-plan"))


def test_ad_library_item_counts_creatives_and_classifies_types_as_one_candidate_card(client, fakes, monkeypatch):
    """P2-9: 3-5 경쟁사 포지셔닝 — 메타(한국 페이지)·구글(국내 광고주)·틱톡(유럽분)의 기간 안 소재를 모아
    소재 카드 하나와 소재 수·유형 비중 Fact를 후보로 만든다. 카드를 채택하면 수치도 함께 채택된다."""
    pid, plan = setup_project(client)
    clear_cache()
    monkeypatch.setattr(research, "AD_SHARE_MIN_N", 3)  # 이 테스트의 표본은 3건
    plan = _set_competitor_alias(client, pid, "경쟁X", "RivalX")
    it = item(plan, "ad_library", "경쟁X")
    assert it["scope_id"] == "3-5" and [c["id"] for c in it["channels"]] == ["ad_library"]

    def facebook_ad_companies(query, **kw):
        fakes._hit("facebook_ad_companies")
        return CallResult(data={"pages": [
            {"page_id": "1", "name": "RivalX", "country": None, "likes": 900000, "ig_username": "rivalx",
             "alias": "rivalx", "verified": True},
            {"page_id": "2", "name": "RivalX Korea", "country": None, "likes": 5000, "ig_username": "rivalx_korea",
             "alias": "RivalXKorea", "verified": False},
            {"page_id": "3", "name": "Other Brand", "country": "KR", "likes": 1, "ig_username": None, "alias": "",
             "verified": False}]}, cost_usd=0.002)

    seen_pages = []

    def facebook_company_ads(page_id, country=None, cursor=None, **kw):
        fakes._hit("facebook_company_ads")
        seen_pages.append((page_id, country))
        ad = lambda i, group, text, start="2026-05-01", img=True: {
            "id": i, "group": group, "url": f"https://www.facebook.com/ads/library?id={i}", "advertiser": "RivalX Korea",
            "format": "image", "text": text, "image_url": f"https://img.example.com/{i}.jpg" if img else None,
            "landing": None, "start": start, "end": None, "active": True}
        return CallResult(data={"ads": [ad("a1", "g1", "11월 특가 40% 할인"), ad("a2", "g1", "11월 특가 40% 할인"),
                                        ad("a3", "g3", "가벼운 캐리어 신제품"), ad("a4", "g4", "옛날 광고", start="2019-01-01")],
                                "cursor": None, "total": 4}, cost_usd=0.002)

    def google_ad_advertisers(query, **kw):
        fakes._hit("google_ad_advertisers")
        assert query == "경쟁X"  # 구글은 한글 이름으로 찾는다
        return CallResult(data={"advertisers": [{"advertiser_id": "AR1", "name": "경쟁X코리아(주)", "region": "KR",
                                                 "ads_estimate": 50},
                                                {"advertiser_id": "AR9", "name": "무관한 회사", "region": "KR",
                                                 "ads_estimate": 500}]}, cost_usd=0.002)

    def google_company_ads(advertiser_id, region=None, cursor=None, **kw):
        fakes._hit("google_company_ads")
        assert advertiser_id == "AR1" and region == "KR"
        return CallResult(data={"ads": [{"id": "CR1", "group": "CR1", "url": "https://adstransparency.google.com/x/CR1",
                                         "advertiser": "경쟁X코리아(주)", "format": "video", "text": "",
                                         "image_url": "https://img.example.com/cr1.jpg", "start": "2026-04-01",
                                         "end": "2026-06-01"}], "cursor": None, "total": 1}, cost_usd=0.002)

    def tiktok_ad_library_search(query, **kw):
        fakes._hit("tiktok_ad_library_search")
        return CallResult(data={"ads": [{"id": "t1", "group": "t1", "url": "https://library.tiktok.com/ads/detail/?ad_id=t1",
                                         "advertiser": "RivalX Europe", "format": "video", "text": "Borse", "image_url": None,
                                         "start": "2026-05-01", "end": "2026-05-09"},
                                        {"id": "t2", "group": "t2", "url": "https://library.tiktok.com/ads/detail/?ad_id=t2",
                                         "advertiser": "Someone Else", "format": "video", "text": "x", "image_url": None,
                                         "start": "2026-05-01", "end": "2026-05-09"}],
                                "cursor": None, "has_more": False}, cost_usd=0.002)

    seen_images = []

    def structured(system, user, schema, **kw):
        if set(schema["properties"]) == {"ads"}:
            fakes._hit("ad_classify")
            seen_images.append(len(kw.get("images") or []))
            rows = []
            for no, line in enumerate(user.split("<ads>\n")[1].split("\n</ads>")[0].split("\n"), start=1):
                rows.append({"no": no, "type": "discount" if "할인" in line else "product"})
            return CallResult(data={"ads": rows}, cost_usd=0.01)
        return fakes.structured(system, user, schema, **kw)

    research.PROVIDERS.update(facebook_ad_companies=facebook_ad_companies, facebook_company_ads=facebook_company_ads,
                              google_ad_advertisers=google_ad_advertisers, google_company_ads=google_company_ads,
                              tiktok_ad_library_search=tiktok_ad_library_search, structured=structured)
    job = ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [it["id"]]}), 202)["job"]
    res = ok(client.get(f"/v1/jobs/{job['id']}"))["result"]["items"][it["id"]]
    assert res["status"] == "succeeded", res
    assert fakes.calls["facebook_ad_search"] == 1  # 한글 이름 광고 검색에 없으면 영문 페이지 검색으로
    assert seen_pages == [("2", "KR")]  # 한국 페이지를 고르고 국내 게재 광고만
    assert res["ads"] == {"meta": 2, "google": 1, "tiktok": 1}  # 같은 소재 묶음은 한 번, 기간 밖·다른 광고주는 뺌
    assert res["out_of_period"] == 1 and res["classified"] == 3 and seen_images == [3]

    mats = [m for m in ok(client.get(f"/v1/projects/{pid}/materials")) if m["section_id"] == "ad_library"]
    assert len(mats) == 1
    card = mats[0]
    assert card["review_status"] == "candidate" and card["entity"] == "경쟁X" and card["scope_id"] == "3-5"
    assert "할인·혜택 33.3%" in card["excerpt"] and "제품 중심 66.7%" in card["excerpt"]
    assert len(card["assets"]) == 3 and all(a["review_status"] == "candidate" for a in card["assets"])
    facts = {(f["metric"], tuple(sorted((f.get("dims") or {}).items()))): f for f in card["facts"]}
    count_meta = facts[("ad_creative_count", (("platform", "meta"),))]
    assert count_meta["value"] == "2" and count_meta["verification_status"] == "candidate"
    share = facts[("ad_creative_type_share", (("n", "3"), ("type", "discount")))]
    assert share["value"] == "33.3" and share["unit"] == "percent"

    ok(client.patch(f"/v1/materials/{card['id']}/review", json={"status": "accepted"}))
    out = ok(client.post(f"/v1/projects/{pid}/materials/accept-all"))
    card = next(m for m in ok(client.get(f"/v1/projects/{pid}/materials")) if m["section_id"] == "ad_library")
    assert card["review_status"] == "accepted"


def test_ad_library_item_finds_the_meta_page_through_korean_ad_search(client, fakes):
    """한글 이름으로 국내 게재 광고를 검색해, 이름이 맞는 광고주 페이지를 고른다(다른 광고주 광고는 뺀다)."""
    pid, plan = setup_project(client)
    clear_cache()
    it = item(plan, "ad_library", "경쟁X")
    ad = lambda i, page, name: {"id": i, "group": i, "url": f"https://www.facebook.com/ads/library?id={i}",
                                "page_id": page, "advertiser": name, "format": "image", "text": f"{name} 신상",
                                "image_url": None, "landing": None, "start": "2026-05-01", "end": None, "active": True}

    def facebook_ad_search(query, country=None, **kw):
        fakes._hit("facebook_ad_search")
        assert query == "경쟁X" and country == "KR"
        return CallResult(data={"ads": [ad("s1", "P1", "경쟁X 공식"), ad("s2", "P1", "경쟁X 공식"),
                                        ad("s3", "P2", "다른 가게")], "cursor": None, "total": 3}, cost_usd=0.002)

    pages = []

    def facebook_company_ads(page_id, country=None, cursor=None, **kw):
        fakes._hit("facebook_company_ads")
        pages.append(page_id)
        return CallResult(data={"ads": [ad("s1", "P1", "경쟁X 공식"), ad("c9", "P1", "경쟁X 공식")], "cursor": None,
                                "total": 2}, cost_usd=0.002)

    research.PROVIDERS.update(facebook_ad_search=facebook_ad_search, facebook_company_ads=facebook_company_ads)
    job = ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [it["id"]]}), 202)["job"]
    res = ok(client.get(f"/v1/jobs/{job['id']}"))["result"]["items"][it["id"]]
    assert pages == ["P1"] and "facebook_ad_companies" not in fakes.calls
    assert res["ads"] == {"meta": 3}  # s1·s2(검색) + c9(페이지), 겹친 s1은 한 번


def test_ad_library_item_without_any_ads_says_so(client, fakes):
    pid, plan = setup_project(client)
    clear_cache()
    it = item(plan, "ad_library", "경쟁X")
    job = ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [it["id"]]}), 202)["job"]
    res = ok(client.get(f"/v1/jobs/{job['id']}"))["result"]["items"][it["id"]]
    assert res["status"] == "failed" and res["errors"][0]["code"] == "NO_MATERIAL"
    assert set(res["platform_notes"]) == {"meta", "google"}  # 플랫폼마다 왜 비었는지 남긴다
    assert fakes.calls["google_ad_advertisers"] == 1 and "google_company_ads" not in fakes.calls


def test_voc_item_reports_access_cause_when_every_post_is_login_walled(client, fakes):
    pid, plan = setup_project(client)
    clear_cache()
    proj = ok(client.get(f"/v1/projects/{pid}"))
    ok(client.patch(f"/v1/projects/{pid}", json={"base_version": proj["version"],
                                                 "changes": {"enabled_slides": proj["config"]["enabled_slides"] + ["5-1"]}}))
    plan = ok(client.get(f"/v1/projects/{pid}/research-plan"))
    it = item(plan, "voc", "브랜드A")

    def search(queries, sites=None, **kw):
        return CallResult(data={"id": "s", "results": [
            {"title": "브랜드A 카페 글", "url": "https://cafe.naver.com/x/9", "snippet": "", "date": "2026-05-03"}]},
                          cost_usd=0.005)

    def fetch_page(url, **kw):
        return Page(url=url, final_url="https://nid.naver.com/nidlogin.login", title="네이버 로그인",
                   text="로그인 후 이용해주세요", content_hash="hlogin", published=None, publisher=None, image_urls=[])

    research.PROVIDERS["search"] = search
    research.PROVIDERS["fetch_page"] = fetch_page
    ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [it["id"]]}), 202)
    sp = ok(client.get(f"/v1/projects/{pid}/slide-plan"))
    slot = next((s for s in sp["plan"] if s["slot_id"].startswith("5-1")), None)
    assert slot is not None and slot["readiness"] == "needs_input" and slot["cause"] == "access"


def test_research_runs_without_a_run_budget(client, fakes, monkeypatch):
    """No RUN_BUDGET_USD = no cap: the run goes ahead and its cost is still recorded."""
    monkeypatch.delenv("RUN_BUDGET_USD", raising=False)
    pid, plan = setup_project(client)
    it = item(plan, "campaign", "경쟁Y")
    job = ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [it["id"]]}), 202)["job"]
    res = ok(client.get(f"/v1/jobs/{job['id']}"))["result"]["items"][it["id"]]
    assert res["status"] != "blocked_budget" and fakes.calls.get("search", 0) > 0
    assert any(r.status == "settled" for r in ledger_rows(pid))


def test_project_list_shows_total_cost(client):
    pid, _ = setup_project(client)
    with SessionLocal() as db:  # cached responses cost nothing, so record spend directly
        db.add_all([ProviderCall(project_id=pid, provider="perplexity", endpoint="search", fingerprint="a",
                                 status="settled", cost_usd=0.005),
                    ProviderCall(project_id=pid, provider="anthropic", endpoint="extract", fingerprint="b",
                                 status="settled", cost_usd=0.0125)])
        db.commit()
    row = next(p for p in ok(client.get("/v1/projects")) if p["id"] == pid)
    assert row["total_cost_usd"] == 0.0175


def test_direction_chat_rewrites_the_item_and_the_plan(client, fakes):
    pid, plan = setup_project(client)
    version = ok(client.get(f"/v1/projects/{pid}"))["version"]
    out = ok(client.post(f"/v1/projects/{pid}/scope/3-7/direction",
                         json={"base_version": version, "message": "경쟁X만, 1년치 팝업 위주로 4개씩"}))
    assert out["reply"].startswith("기간을") and out["project_version"] == version + 1
    sc = out["scope"]
    assert sc["period"] == "months" and sc["months"] == 12 and sc["channels"] == ["web", "instagram"]  # unknown dropped
    assert sc["targets"] == ["경쟁X"] and sc["max_items"] == 4 and sc["keywords"] == ["팝업스토어"]
    assert sc["direction"][-1] == "팝업·오프라인 행사 사례를 먼저 봅니다."
    items = [i for i in ok(client.get(f"/v1/projects/{pid}/research-plan"))["items"] if i["scope_id"] == "3-7"]
    assert [i["entity"] for i in items] == ["경쟁X"] and items[0]["period_start"] == "2025-10-01"
    # A stale version is refused instead of overwriting someone else's change.
    r = client.post(f"/v1/projects/{pid}/scope/3-7/direction", json={"base_version": version, "message": "x"})
    assert r.status_code == 409


def test_card_ai_help_summary_suggestions_polish_chat(client, fakes):
    pid, plan = setup_project(client)
    it = item(plan, "campaign", "경쟁X")
    with SessionLocal() as db:  # an earlier test caches search results that point elsewhere
        db.query(ProviderCache).delete()
        db.commit()
    ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [it["id"]]}), 202)
    article = next(m for m in ok(client.get(f"/v1/projects/{pid}/materials")) if m["source"]["url"] == "https://news.example.com/a1")

    # A hand-made card gets its 해석 요약 on request (page fetched once and kept).
    manual = ok(client.post(f"/v1/projects/{pid}/materials", json={"title": "직접", "url": "https://example.com/m",
                                                                    "section_id": "campaign"}), 201)
    assert ok(client.post(f"/v1/materials/{manual['id']}/summary"))["summary"] == "직접 만든 카드의 요약입니다."

    # Sentence ideas: only the one quoting the page verbatim, with no bare number, survives.
    sug = ok(client.post(f"/v1/materials/{article['id']}/claim-suggestions"))["suggestions"]
    assert [s["text"] for s in sug] == ["성수동 팝업에 신제품 체험 공간 배치"]
    c = ok(client.post(f"/v1/materials/{article['id']}/claims", json={**sug[0], "accept": True}), 201)
    assert c["review_status"] == "accepted" and c["author"] == "ai" and c["quote"]

    # 다듬기 keeps the fact token; a rewrite that changes numbers is refused.
    fid = article["facts"][0]["id"]
    text = "조회 {{" + fid + "}} 규모의 체험형 확산"
    assert ok(client.post(f"/v1/materials/{article['id']}/polish", json={"text": text}))["text"].count(fid) == 1
    r = client.post(f"/v1/materials/{article['id']}/polish", json={"text": text + " 깨기"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "POLISH_CHANGED_FACTS"

    # Chat: the page does not say, so it searches once and cites only results that exist.
    out = ok(client.post(f"/v1/materials/{article['id']}/chat", json={"message": "방문객이 언제 몰렸어?"}))
    assert out["searched"] == "경쟁X 팝업 방문객" and out["answer"].startswith("추가 기사")
    assert out["sources"] == [{"title": "경쟁X 성수 팝업", "url": "https://news.example.com/a1"}]


def test_outline_reads_the_deck_and_slide_feedback_changes_it(client, fakes):
    pid, _ = setup_project(client)
    for b in ok(client.post(f"/v1/projects/{pid}/imports/sample"), 201):
        ok(client.post(f"/v1/imports/{b['id']}/review", json={"action": "accept"}))
    flow = ok(client.get(f"/v1/projects/{pid}/outline"))
    slides = [x for x in flow["flow"] if x["kind"] == "slide"]
    assert any(x["kind"] == "section" for x in flow["flow"]) and flow["missing"]  # empty slides are listed, not shown
    share = next(x for x in slides if x["slide_id"] == "2-8a")
    assert share["lead"] and share["points"] and share["source"] and not share["edited"]

    out = ok(client.post(f"/v1/projects/{pid}/outline/2-8a/feedback", json={"message": "리드를 좀 더 부드럽게"}))
    assert out["action"] == "rewrite_lead"
    share = next(x for x in ok(client.get(f"/v1/projects/{pid}/outline"))["flow"] if x.get("slide_id") == "2-8a")
    assert share["edited"] and share["lead"] == "브랜드 검색 점유 우위가 줄어든 흐름"

    # A headline that breaks the rules (bare number) is retried, then left alone with a plain reason.
    out = ok(client.post(f"/v1/projects/{pid}/outline/2-8a/feedback", json={"message": "깨기"}))
    assert out["action"] == "none" and "규칙" in out["reply"]
    out = ok(client.post(f"/v1/projects/{pid}/outline/2-8a/feedback", json={"message": "순서를 앞으로"}))
    assert out["action"] == "none" and "순서" in out["reply"]

    out = ok(client.post(f"/v1/projects/{pid}/outline/2-8a/feedback", json={"message": "이 장은 빼줘"}))
    assert out["action"] == "omit" and out["slot_id"] == "2-8a"
    after = ok(client.get(f"/v1/projects/{pid}/outline"))
    assert "2-8a" not in [x.get("slide_id") for x in after["flow"]] and after["omitted"][0]["slot_id"] == "2-8a"
    assert client.post(f"/v1/projects/{pid}/outline/nope/feedback", json={"message": "x"}).status_code == 404


def test_accept_all_takes_waiting_cards_and_leaves_doubtful_ones(client, fakes):
    pid, _ = setup_project(client)
    plain = ok(client.post(f"/v1/projects/{pid}/materials", json={"title": "직접 넣은 사례", "section_id": "campaign"}), 201)
    doubtful = ok(client.post(f"/v1/projects/{pid}/materials", json={"title": "기간 애매", "section_id": "campaign"}), 201)
    with SessionLocal() as db:
        from app.models import Material
        db.get(Material, doubtful["id"]).review_reason = "기간 확인 필요: 활동일·발행일 미확인"
        db.commit()
    c = ok(client.post(f"/v1/materials/{plain['id']}/claims", json={"kind": "fact", "text": "팝업 운영"}), 201)
    out = ok(client.post(f"/v1/projects/{pid}/materials/accept-all"))
    assert out == {"accepted": 1, "left": 1}
    m = ok(client.get(f"/v1/materials/{plain['id']}"))
    assert m["review_status"] == "accepted" and m["claims"][0]["review_status"] == "accepted" and m["claims"][0]["id"] == c["id"]
    assert ok(client.get(f"/v1/materials/{doubtful['id']}"))["review_status"] == "candidate"


def test_results_that_never_name_the_brand_are_dropped_before_fetching(client, fakes):
    pid, plan = setup_project(client)
    it = item(plan, "campaign", "경쟁X")
    with SessionLocal() as db:
        db.query(ProviderCache).delete()
        db.commit()
    original = fakes.search

    def noisy(queries, **kw):
        res = original(queries, **kw)
        res.data = {**res.data, "results": [
            {"title": "코웨이, 연중 최대 프로모션 개최", "url": "https://n.example.com/coway", "snippet": "렌탈료 할인", "date": "2026-03-01"},
            {"title": "패션 브리핑", "url": "https://n.example.com/brief", "snippet": "경쟁 X 가 새 컬렉션을 공개", "date": "2026-03-02"},
            *res.data["results"]]}
        return res

    research.PROVIDERS["search"] = noisy
    job = ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [it["id"]]}), 202)["job"]
    res = ok(client.get(f"/v1/jobs/{job['id']}"))["result"]["items"][it["id"]]
    urls = [m["source"]["url"] for m in ok(client.get(f"/v1/projects/{pid}/materials"))]
    assert "https://n.example.com/coway" not in urls and res["off_topic"] >= 1
    assert "https://n.example.com/brief" in urls  # named in the snippet (spacing ignored) still counts


def test_synthesis_writes_summary_pages_from_the_deck(client, fakes):
    pid, _ = setup_project(client)
    for b in ok(client.post(f"/v1/projects/{pid}/imports/sample"), 201):
        ok(client.post(f"/v1/imports/{b['id']}/review", json={"action": "accept"}))
    brand_id = ok(client.get(f"/v1/projects/{pid}"))["config"]["brands"][0]["id"]

    out = ok(client.post(f"/v1/projects/{pid}/synthesis", json={"brand_id": brand_id, "instruction": "검색 위주로"}))
    assert out["version"] == 1 and out["active"] and not out["stale"]
    assert out["types"] == ["insight"]  # 기본값
    assert [line["text"] for line in out["data"]["insight"]["competitor"]] == ["경쟁 세트 안 검색 점유 우위 축소"]
    assert out["data"]["insight"]["competitor"][0]["ref"] == "2-8a"
    assert any("숫자" in d for d in out["dropped"]) and any("Z-9" in d for d in out["dropped"])
    flow = ok(client.get(f"/v1/projects/{pid}/outline"))["flow"]
    ids = [x.get("slide_id") for x in flow if x["kind"] == "slide"]
    assert ids[0] == "ES" and "INSIGHT" in ids and "SWOT" not in ids  # 고른 유형만 만들어진다
    issues = ok(client.get(f"/v1/projects/{pid}/slide-plan"))["qc"]["issues"]
    assert not [i for i in issues if i["slide_id"] in ("ES", "INSIGHT") and i["severity"] == "block"], issues

    # 다시 쓰기: 결과가 이미 있어도 다시 쓸 수 있고, 덮어쓰지 않고 새 버전으로 남는다(버그 수정 확인).
    out2 = ok(client.post(f"/v1/projects/{pid}/synthesis",
                          json={"brand_id": brand_id, "types": ["insight", "swot"], "instruction": "검색 위주로"}))
    assert out2["version"] == 2 and out2["active"] and out2["types"] == ["insight", "swot"]
    versions = ok(client.get(f"/v1/projects/{pid}/synthesis"))
    assert [(v["version"], v["active"]) for v in versions] == [(2, True), (1, False)]
    ids2 = [x.get("slide_id") for x in ok(client.get(f"/v1/projects/{pid}/outline"))["flow"] if x["kind"] == "slide"]
    assert "SWOT" in ids2  # 새 버전의 유형이 반영됨

    # 되돌리기: 새로 만들지 않고 이전 버전을 다시 활성으로.
    v1 = next(v for v in versions if v["version"] == 1)
    back = ok(client.post(f"/v1/synthesis-runs/{v1['id']}/activate"))
    assert back["active"] and back["version"] == 1
    versions = ok(client.get(f"/v1/projects/{pid}/synthesis"))
    assert [(v["version"], v["active"]) for v in versions] == [(2, False), (1, True)]
    ids3 = [x.get("slide_id") for x in ok(client.get(f"/v1/projects/{pid}/outline"))["flow"] if x["kind"] == "slide"]
    assert "SWOT" not in ids3  # v1에는 insight만 있었으므로 되돌아감

    ok(client.delete(f"/v1/projects/{pid}/synthesis", params={"brand_id": brand_id}))
    assert "ES" not in [x.get("slide_id") for x in ok(client.get(f"/v1/projects/{pid}/outline"))["flow"]]


def test_deck_build_creates_default_insight_once_and_reuses_fingerprint(client, fakes):
    pid, _ = setup_project(client)
    for batch in ok(client.post(f"/v1/projects/{pid}/imports/sample"), 201):
        ok(client.post(f"/v1/imports/{batch['id']}/review", json={"action": "accept"}))
    assert ok(client.get(f"/v1/projects/{pid}/synthesis")) == []

    first = ok(client.post(f"/v1/projects/{pid}/deck-builds"), 202)
    job = ok(client.get(f"/v1/jobs/{first['job']['id']}"))
    assert job["state"] == "succeeded" and job["result"]["synthesis"]["generated"]
    deck = ok(client.get(f"/v1/decks/{first['deck_id']}"))
    ids = [slide["slide_id"] for slide in deck["spec"]["slides"]]
    assert "ES" in ids and "INSIGHT" in ids
    assert ids.index("ES") < ids.index("INSIGHT")
    runs = ok(client.get(f"/v1/projects/{pid}/synthesis"))
    assert len(runs) == 1 and runs[0]["active"] and runs[0]["types"] == ["insight"]

    second = ok(client.post(f"/v1/projects/{pid}/deck-builds", json={"confirm_pending": True}), 202)
    job2 = ok(client.get(f"/v1/jobs/{second['job']['id']}"))
    assert job2["state"] == "succeeded" and job2["result"]["synthesis"]["cached"]
    assert len(ok(client.get(f"/v1/projects/{pid}/synthesis"))) == 1


def test_synthesis_scopes_pages_to_their_own_brand(client, fakes, monkeypatch):
    """자사 브랜드가 여럿이면 브랜드마다 따로 — 다른 브랜드의 본문 장표가 섞이지 않는다."""
    from app.models import Project

    p = ok(client.post("/v1/projects", json={
        "name": "멀티 브랜드", "client": "고객", "period": {"start": "2026-01-01", "end": "2026-09-30"},
        "brands": [{"id": "B1", "name": "브랜드A", "competitors": ["경쟁X1"], "categories": ["러기지"]},
                  {"id": "B2", "name": "브랜드B", "competitors": ["경쟁Y1"], "categories": ["러기지"]}]}), 201)
    pid = p["id"]

    pages = [{"id": "1-1", "chapter": "company", "title": "자사 채널 A", "lead": "A 운영 현황", "points": [], "brand": "브랜드A"},
             {"id": "1-2", "chapter": "company", "title": "자사 채널 B", "lead": "B 운영 현황", "points": [], "brand": "브랜드B"},
             {"id": "3-1", "chapter": "customer", "title": "검색 추이", "lead": "검색 추이 공유", "points": []}]
    monkeypatch.setattr(synthesis, "body_pages", lambda db, project: pages)

    seen: list[str] = []

    def fake_structured(system, user, schema, **kw):
        seen.append(user)
        return CallResult(data={"es_company": [], "es_competitor": [], "es_customer": [], "task": "", "insights": []},
                          usage={"model": "fake"}, cost_usd=0.001)

    synthesis.STRUCTURED.clear()
    synthesis.STRUCTURED.append(fake_structured)
    try:
        with SessionLocal() as db:
            project = db.get(Project, pid)
            synthesis.generate(db, project, "B1", ["insight"])
            synthesis.generate(db, project, "B2", ["insight"])
            db.rollback()
    finally:
        synthesis.STRUCTURED.clear()

    assert "1-1" in seen[0] and "3-1" in seen[0] and "1-2" not in seen[0]  # B1: 자신의 장표 + 공유 장표만
    assert "1-2" in seen[1] and "3-1" in seen[1] and "1-1" not in seen[1]  # B2: 자신의 장표 + 공유 장표만


def test_articles_naming_a_competitor_another_way_are_kept(client, fakes):
    pid, plan = setup_project(client)
    clear_cache()
    fakes.search_name = "CompetitorX"  # every article uses the English name only
    it = item(plan, "campaign", "경쟁X")
    job = ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [it["id"]]}), 202)["job"]
    res = ok(client.get(f"/v1/jobs/{job['id']}"))["result"]["items"][it["id"]]
    assert res["status"] == "succeeded" and res["created"] == 2 and res["off_topic"] == 0
    brand = ok(client.get(f"/v1/projects/{pid}"))["config"]["brands"][0]
    assert brand["entity_aliases"]["경쟁X"] == ["CompetitorX"]  # filled by the AI, the name itself left out


def test_no_material_about_the_subject_is_reported_and_not_bulk_confirmed(client, fakes):
    pid, plan = setup_project(client)
    clear_cache()
    fakes.search_name = "다른브랜드"
    it = item(plan, "campaign", "경쟁X")
    job = ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [it["id"]]}), 202)["job"]
    res = ok(client.get(f"/v1/jobs/{job['id']}"))["result"]["items"][it["id"]]
    assert res["status"] == "failed" and res.get("created", 0) == 0
    assert res["errors"][0]["code"] == "NO_MATERIAL" and res["retried_aliases"] == ["CompetitorX"]
    assert fakes.calls["aliases"] == 1
    ok(client.post(f"/v1/projects/{pid}/research-plan/accept-all"))
    after = item(ok(client.get(f"/v1/projects/{pid}/research-plan")), "campaign", "경쟁X")
    assert after["review_status"] == "pending"


def test_create_project_fills_industry_and_official_accounts(client, fakes):
    clear_cache()  # another test may have cached a request with the same (provider, endpoint, name)
    p = ok(client.post("/v1/projects", json={
        "name": "브랜드 카드 테스트", "client": "고객", "period": {"start": "2026-01-01", "end": "2026-09-30"},
        "brands": [{"id": "B1", "name": "브랜드A", "competitors": ["경쟁X"], "categories": ["러기지"]}]}), 201)
    brand = p["config"]["brands"][0]
    assert brand["industry"] == "패션"  # AI가 채움, 사람이 입력하지 않음
    assert [prof["status"] for prof in brand["official_profiles"]] == ["candidate"]  # 확인 전까지는 후보일 뿐
    assert brand["competitor_profiles"]["경쟁X"][0]["channel"] == "instagram"
    assert fakes.calls["industry"] == 1
    assert fakes.calls["official_accounts"] == 2  # self + 경쟁X, 한 번씩
    # Phase 2 커머스 리뷰: 대표 상품도 같은 방식으로 후보만 채운다(확정은 사람이).
    assert [p["status"] for p in brand["hero_products"]] == ["candidate"]
    assert brand["hero_products"][0]["name"] == "에어맥스 95"
    assert brand["competitor_hero_products"]["경쟁X"][0]["status"] == "candidate"
    assert fakes.calls["hero_products"] == 2  # self + 경쟁X, 한 번씩
    # 피드백 #1(업종별 variation): "패션"은 이미 커튜레이션된 프로필이 있어 AI 후보가 필요 없다.
    assert brand.get("industry_keywords") == []
    assert "industry_keywords" not in fakes.calls

    # A planner-set industry is never overwritten, and an entity with an account already on file
    # (even just a candidate) is not searched again.
    pid = p["id"]
    patched = ok(client.patch(f"/v1/projects/{pid}", json={"base_version": p["version"], "changes": {
        "brands": [{**brand, "industry": "기타"}]}}))
    assert patched["config"]["brands"][0]["industry"] == "기타"
    assert fakes.calls["industry"] == 1  # still just the one call from create
    assert fakes.calls["official_accounts"] == 2
    assert fakes.calls["hero_products"] == 2  # a brand/competitor with a candidate already on file isn't re-searched
    # "기타"는 프로필에 키워드 초안이 없어 AI가 후보 키워드를 낸다 — 확인 전까지는 시장 조사 검색에 쓰이지 않는다.
    # (키워드 초안이 있는 업종은 외부 호출 없이 초안을 후보로 낸다 — tests/unit/test_industry_profiles.py)
    beauty_brand = patched["config"]["brands"][0]
    assert [k["status"] for k in beauty_brand["industry_keywords"]] == ["candidate"]
    assert beauty_brand["industry_keywords"][0]["text"] == "트래블룩"
    assert fakes.calls["industry_keywords"] == 1


def test_missing_slides_say_why_and_what_to_do(client, fakes):
    pid, plan = setup_project(client)
    clear_cache()
    it = item(plan, "campaign", "경쟁X")
    ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [it["id"]]}), 202)
    gaps = {s["slot_id"]: s for s in ok(client.get(f"/v1/projects/{pid}/slide-plan"))["plan"] if s["readiness"] == "needs_input"}
    assert gaps["C1c"]["cause"] == "adopt"  # 경쟁X's cards are waiting for a person
    # 3-1(인플루언서)은 이제 입력이 없어도 브랜드 이름으로 찾아보므로 '설정 필요'가 아니라 '수집 필요'.
    assert gaps["3-1-B1"]["cause"] == "collect"
    # 검색 점유는 이제 데이터랩으로 자동 수집 — CSV 업로드가 아니라 '수집 필요', 다시 모을 항목은 검색 항목.
    assert gaps["2-8a"]["cause"] == "collect" and gaps["2-8a"]["item_ids"] == [item(plan, "search")["id"]]
    self_item = item(plan, "campaign", "브랜드A")
    assert gaps["C1"]["cause"] == "collect" and gaps["C1"]["item_ids"] == [self_item["id"]]
    assert gaps["5-recap"]["cause"] is None
    missing = {m["slot_id"]: m for m in ok(client.get(f"/v1/projects/{pid}/outline"))["missing"]}
    assert missing["C1c"]["cause"] == "adopt" and missing["C1c"]["action"]


def test_competitor_ad_mix_checks_and_stores_latest_only(client, fakes, monkeypatch):
    """Phase 3-2 경쟁사 포지셔닝 보강: 확인할 때마다 그 경쟁사의 최신 1건으로 남는다."""
    from app.services import ad_library

    pid, plan = setup_project(client)
    brand_id = ok(client.get(f"/v1/projects/{pid}"))["config"]["brands"][0]["id"]

    monkeypatch.setattr(ad_library, "fetch_ad_mix",
                        lambda entity, country="KR": {"status": "unavailable", "reason": "접근 불가 — 봇 확인 페이지로 막힘"})
    out = ok(client.post(f"/v1/projects/{pid}/ad-mix", json={"brand_id": brand_id, "entity": "경쟁X"}))
    assert out["status"] == "unavailable" and out["mix"] is None

    bad = ok(client.post(f"/v1/projects/{pid}/ad-mix", json={"brand_id": brand_id, "entity": "없는경쟁사"}), 422)
    assert bad["error"]["code"] == "INVALID_INPUT"

    monkeypatch.setattr(ad_library, "fetch_ad_mix",
                        lambda entity, country="KR": {"status": "ok", "mix": {"review": 40, "influencer": 35, "product": 25},
                                                      "ad_count": 20})
    out2 = ok(client.post(f"/v1/projects/{pid}/ad-mix", json={"brand_id": brand_id, "entity": "경쟁X"}))
    assert out2["status"] == "ok" and out2["mix"] == {"review": 40, "influencer": 35, "product": 25}

    rows = ok(client.get(f"/v1/projects/{pid}/ad-mix"))
    assert len(rows) == 1 and rows[0]["id"] == out["id"] == out2["id"]  # 경쟁사당 최신 1건만
