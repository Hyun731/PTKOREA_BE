"""Minimal live check of each provider with the real .env keys (DEVELOPMENT_PLAN 2 API 연결 순서).

One search, one page fetch, one extraction, one YouTube video + channel. Prints outcomes and
costs, never key values, and writes nothing to the database.

    .venv/bin/python tools/live_smoke.py "샘소나이트 캠페인 2026"
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.config  # noqa: E402,F401  (loads .env)
from app.services.research import EXTRACT_SCHEMA, EXTRACT_SYSTEM, validate_extraction  # noqa: E402
from integrations.anthropic.client import structured  # noqa: E402
from integrations.base import ProviderError  # noqa: E402
from integrations.fetch.page import fetch_page  # noqa: E402
from integrations.perplexity.client import search  # noqa: E402
from integrations.scrapecreators.client import platform_of, youtube_channel, youtube_video  # noqa: E402

query = sys.argv[1] if len(sys.argv) > 1 else "샘소나이트 캠페인 2026"
total = 0.0


def step(name, fn):
    global total
    t = time.time()
    try:
        res = fn()
    except ProviderError as exc:
        print(f"[{name}] 실패 {exc.code}: {exc.message}")
        return None
    total += getattr(res, "cost_usd", 0) or 0
    print(f"[{name}] 성공 {time.time() - t:.1f}s" + (f" · ${res.cost_usd:.4f}{' (추정)' if res.cost_is_estimate else ''} · {res.usage}" if hasattr(res, "usage") else ""))
    return res


s = step("perplexity.search", lambda: search([query], max_results=5, country="KR", languages=["ko"]))
results = s.data["results"] if s else []
for r in results:
    print(f"   - {r['title'][:50]} | {r['url'][:80]} | {r['date']}")

page = None
for r in results:
    if platform_of(r["url"]) is None:
        try:
            page = fetch_page(r["url"])
            print(f"[fetch_page] 성공 {r['url'][:70]} · 본문 {len(page.text)}자 · 발행 {page.published} · 이미지 {len(page.image_urls)}")
            break
        except ProviderError as exc:
            print(f"[fetch_page] 실패 {r['url'][:70]}: {exc.code} {exc.message}")

if page:
    user = f"조사 대상: {query.split()[0]}\n조사 질문: {query} 캠페인·활동 사례\n원문 URL: {page.final_url}\n<page>\n{page.text[:12000]}\n</page>"
    a = step("anthropic.extract", lambda: structured(EXTRACT_SYSTEM, user, EXTRACT_SCHEMA, max_tokens=4000))
    if a:
        facts, claims, issues = validate_extraction(a.data, page.text)
        print(f"   relevant={a.data.get('relevant')} 수치 {len(facts)}/{len(a.data.get('facts', []))} 통과 · 문장 {len(claims)}/{len(a.data.get('claims', []))} 통과")
        for c in claims:
            print(f"   [{c['kind']}] {c['text']}")
        for i in issues[:5]:
            print(f"   제외: {i}")

yt = next((r["url"] for r in results if platform_of(r["url"]) == "youtube"), None) or "https://www.youtube.com/watch?v=jNQXAC9IVRw"
v = step("scrapecreators.youtube_video", lambda: youtube_video(yt))
if v:
    d = v.data
    print(f"   {d['title'][:40]} · {d['creator']} · 게시 {d['posted_at']} · 조회 {d['views']} · 좋아요 {d['likes']} · 댓글 {d['comments']} · 유료 프로모션 표시 {d['paid_promotion']}")
    if d.get("channel_url"):
        c = step("scrapecreators.youtube_channel", lambda: youtube_channel(url=d["channel_url"]))
        if c:
            print(f"   구독자 {c.data['subscribers']}")
print(f"합계(추정 포함) ${total:.4f}")
