"""ScrapeCreators public post metrics (PRD 6). Values are observations at fetch time, not
historical. Instagram plays are Instagram-only (never Facebook-combined); YouTube
isPaidPromotion is a disclosure flag, not ad-spend evidence.
Docs: https://docs.scrapecreators.com/v1/instagram/post/ , /v1/youtube/video/ , /v1/youtube/channel"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlparse

import httpx

from integrations.base import CallResult, ProviderError, request_json

BASE = "https://api.scrapecreators.com/v1"
BASE_V2 = "https://api.scrapecreators.com/v2"
BASE_V3 = "https://api.scrapecreators.com/v3"
EST_COST_PER_CREDIT = 0.002  # plan price not confirmed: estimate, units recorded as credits
SHORTS_MAX_SECONDS = 60  # YouTube's own Shorts definition


def _key() -> str:
    key = os.environ.get("SCRAPECREATORS_API_KEY")
    if not key:
        raise ProviderError("PROVIDER_AUTH", "SCRAPECREATORS_API_KEY가 설정되지 않았습니다")
    return key


def _get(path: str, params: dict, transport, base: str = BASE) -> dict:
    return request_json("ScrapeCreators", "GET", f"{base}{path}", headers={"x-api-key": _key()}, params=params,
                        transport=transport)


def _credits(data: dict) -> int:
    return 0 if data.get("cached") else 1


def platform_of(url: str) -> Optional[str]:
    host = (urlparse(url).hostname or "").lower()
    if host.endswith("instagram.com"):
        return "instagram"
    if host.endswith("youtube.com") or host == "youtu.be":
        return "youtube"
    return None


def _int(v: Any) -> Optional[int]:
    if v is None or isinstance(v, bool):
        return None
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return n if n >= 0 else None


def instagram_post(url: str, transport: Optional[httpx.BaseTransport] = None) -> CallResult:
    data = _get("/instagram/post", {"url": url, "trim": "false"}, transport)
    m = (data.get("data") or {}).get("xdt_shortcode_media") or {}
    if not m:
        raise ProviderError("SOURCE_UNAVAILABLE", "Instagram 게시물을 찾을 수 없습니다(비공개·삭제 가능)")
    caption_edges = ((m.get("edge_media_to_caption") or {}).get("edges") or [])
    caption = caption_edges[0]["node"]["text"] if caption_edges else ""
    hidden = bool(m.get("like_and_view_counts_disabled"))
    ts = m.get("taken_at_timestamp")
    posted = datetime.fromtimestamp(int(ts), tz=timezone.utc).date().isoformat() if ts else None
    owner = m.get("owner") or {}
    post = {
        "platform": "instagram", "url": url, "post_id": m.get("shortcode") or url,
        "posted_at": posted, "title": caption[:200], "creator": owner.get("username") or "",
        "followers": _int((owner.get("edge_followed_by") or {}).get("count")),
        "views": _int(m.get("video_play_count")),  # Instagram-only plays; None for photos
        "likes": None if hidden else _int((m.get("edge_media_preview_like") or {}).get("count")),
        "comments": _int((m.get("edge_media_to_parent_comment") or {}).get("count")),
        "likes_hidden": hidden, "paid_promotion": None,
        "image_urls": [u for u in [m.get("display_url"), m.get("thumbnail_src")] if u],
        "metric_scope": "instagram_only",
    }
    return CallResult(data=post, usage={"credits": _credits(data)}, cost_usd=_credits(data) * EST_COST_PER_CREDIT)


def instagram_post_comments(url: str, *, cursor: Optional[str] = None,
                            transport: Optional[httpx.BaseTransport] = None) -> CallResult:
    """공개 게시물의 댓글 원문(피드백 #2: 댓글 감성 분석) — docs.scrapecreators.com의 문서화된
    GET /v2/instagram/post/comments. 페이지당 한 번만 부른다(전수 수집 아님 — 표본)."""
    params = {"url": url}
    if cursor:
        params["cursor"] = cursor
    data = _get("/instagram/post/comments", params, transport, base=BASE_V2)
    rows = []
    for c in data.get("comments") or []:
        text = (c.get("text") or "").strip()
        if not text:
            continue
        rows.append({"id": c.get("id"), "text": text, "posted_at": (c.get("created_at") or "")[:10],
                    "likes": _int(c.get("comment_like_count"))})
    return CallResult(data={"comments": rows, "cursor": data.get("cursor")},
                      usage={"credits": _credits(data)}, cost_usd=_credits(data) * EST_COST_PER_CREDIT)


def _comment_result(data: dict, rows: list[dict], cursor_keys: tuple[str, ...]) -> CallResult:
    cursor = next((data.get(key) for key in cursor_keys if data.get(key)), None)
    return CallResult(data={"comments": rows, "cursor": str(cursor) if cursor else None},
                      usage={"credits": _credits(data)}, cost_usd=_credits(data) * EST_COST_PER_CREDIT)


def youtube_video_comments(url: str, *, cursor: Optional[str] = None,
                           transport: Optional[httpx.BaseTransport] = None) -> CallResult:
    params = {"url": url}
    if cursor:
        params["continuationToken"] = cursor
    data = _get("/youtube/video/comments", params, transport)
    rows = []
    for comment in data.get("comments") or []:
        text = (comment.get("text") or comment.get("content") or comment.get("comment") or "").strip()
        if text:
            rows.append({"id": comment.get("id"), "text": text,
                         "posted_at": str(comment.get("publishedAt") or comment.get("published_at") or "")[:10],
                         "likes": _int(comment.get("likeCount") or comment.get("likes"))})
    return _comment_result(data, rows, ("continuationToken", "cursor"))


def tiktok_video_comments(url: str, *, cursor: Optional[str] = None,
                          transport: Optional[httpx.BaseTransport] = None) -> CallResult:
    params = {"url": url}
    if cursor:
        params["cursor"] = cursor
    data = _get("/tiktok/video/comments", params, transport)
    rows = []
    for comment in data.get("comments") or []:
        text = (comment.get("text") or "").strip()
        if text:
            rows.append({"id": comment.get("cid") or comment.get("id"), "text": text,
                         "posted_at": _ts_date(comment.get("create_time")),
                         "likes": _int(comment.get("digg_count") or comment.get("like_count"))})
    return _comment_result(data, rows, ("cursor", "max_cursor"))


def facebook_post_comments(url: str, *, cursor: Optional[str] = None,
                           transport: Optional[httpx.BaseTransport] = None) -> CallResult:
    params = {"url": url}
    if cursor:
        params["cursor"] = cursor
    data = _get("/facebook/post/comments", params, transport)
    rows = []
    for comment in data.get("comments") or []:
        text = (comment.get("message") or comment.get("text") or "").strip()
        if text:
            rows.append({"id": comment.get("id"), "text": text,
                         "posted_at": str(comment.get("created_time") or comment.get("created_at") or "")[:10],
                         "likes": _int(comment.get("like_count") or comment.get("reactionCount"))})
    return _comment_result(data, rows, ("cursor",))


def instagram_profile(handle: str, transport: Optional[httpx.BaseTransport] = None) -> CallResult:
    """Follower count for a creator: the post endpoint leaves owner followers empty."""
    data = _get("/instagram/profile", {"handle": handle.lstrip("@")}, transport)
    user = (data.get("data") or {}).get("user") or {}
    return CallResult(data={"followers": _int((user.get("edge_followed_by") or {}).get("count")),
                            "name": user.get("full_name") or user.get("username")},
                      usage={"credits": _credits(data)}, cost_usd=_credits(data) * EST_COST_PER_CREDIT)


def youtube_video(url: str, transport: Optional[httpx.BaseTransport] = None) -> CallResult:
    data = _get("/youtube/video", {"url": url}, transport)
    if not data.get("id"):
        raise ProviderError("SOURCE_UNAVAILABLE", "YouTube 영상을 찾을 수 없습니다")
    channel = data.get("channel") or {}
    publish = str(data.get("publishDate") or "")[:10] or None
    post = {
        "platform": "youtube", "url": url, "post_id": data["id"], "posted_at": publish,
        "title": (data.get("title") or "")[:200], "creator": channel.get("title") or channel.get("handle") or "",
        "channel_url": channel.get("url"), "channel_handle": channel.get("handle"), "followers": None,
        "views": _int(data.get("viewCountInt")), "likes": _int(data.get("likeCountInt")),
        "comments": _int(data.get("commentCountInt")), "likes_hidden": False,
        "paid_promotion": bool(data.get("isPaidPromotion")),
        "image_urls": [u for u in [data.get("thumbnail")] if u], "metric_scope": "youtube",
    }
    return CallResult(data=post, usage={"credits": _credits(data)}, cost_usd=_credits(data) * EST_COST_PER_CREDIT)


def youtube_channel(*, url: Optional[str] = None, handle: Optional[str] = None,
                    transport: Optional[httpx.BaseTransport] = None) -> CallResult:
    params = {"url": url} if url else {"handle": (handle or "").lstrip("@")}
    data = _get("/youtube/channel", params, transport)
    return CallResult(data={"subscribers": _int(data.get("subscriberCount")), "name": data.get("name")},
                      usage={"credits": _credits(data)}, cost_usd=_credits(data) * EST_COST_PER_CREDIT)


def _x_date(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%a %b %d %H:%M:%S %z %Y").date().isoformat()
    except ValueError:
        return None


def twitter_search_posts(query: str, *, cursor: Optional[str] = None,
                         transport: Optional[httpx.BaseTransport] = None) -> CallResult:
    """공개 X(트위터) 게시물 키워드 검색(피드백 #5: SNS 네이티브 검색) — 문서화된
    GET /v1/twitter/search/posts. 검색 결과 자체에 본문이 있어 별도 페이지 수집이 필요 없다."""
    params = {"query": query}
    if cursor:
        params["cursor"] = cursor
    data = _get("/twitter/search/posts", params, transport)
    rows = []
    for t in data.get("posts") or []:
        legacy = t.get("legacy") or {}
        text = (legacy.get("full_text") or "").strip()
        if not text:
            continue
        user = (((t.get("core") or {}).get("user_results") or {}).get("result") or {}).get("core") or {}
        rows.append({"url": t.get("url"), "text": text, "posted_at": _x_date(legacy.get("created_at")),
                    "author": user.get("screen_name"), "likes": _int(legacy.get("favorite_count"))})
    return CallResult(data={"posts": rows, "cursor": data.get("cursor")},
                      usage={"credits": _credits(data)}, cost_usd=_credits(data) * EST_COST_PER_CREDIT)


def threads_search(query: str, *, start_date: Optional[str] = None, end_date: Optional[str] = None,
                   transport: Optional[httpx.BaseTransport] = None) -> CallResult:
    """공개 Threads 게시물 키워드 검색(피드백 #5) — 문서화된 GET /v1/threads/search.
    start_date/end_date는 YYYY-MM-DD."""
    params: dict[str, Any] = {"query": query}
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date
    data = _get("/threads/search", params, transport)
    rows = []
    for t in data.get("posts") or []:
        text = ((t.get("caption") or {}).get("text") or "").strip()
        if not text:
            continue
        ts = t.get("taken_at")
        posted = datetime.fromtimestamp(int(ts), tz=timezone.utc).date().isoformat() if ts else None
        rows.append({"url": t.get("url"), "text": text, "posted_at": posted,
                    "author": (t.get("user") or {}).get("username"), "likes": _int(t.get("like_count"))})
    return CallResult(data={"posts": rows}, usage={"credits": _credits(data)}, cost_usd=_credits(data) * EST_COST_PER_CREDIT)


def instagram_user_posts(handle: str, *, next_max_id: Optional[str] = None,
                         transport: Optional[httpx.BaseTransport] = None) -> CallResult:
    """One page of the account's own feed (채널 인벤토리 2-1/2-4) — not a single post lookup."""
    params = {"handle": handle.lstrip("@"), "trim": "true"}
    if next_max_id:
        params["next_max_id"] = next_max_id
    data = _get("/instagram/user/posts", params, transport, base=BASE_V2)
    posts = []
    for m in data.get("items") or []:
        ts = m.get("taken_at")
        posted = datetime.fromtimestamp(int(ts), tz=timezone.utc).date().isoformat() if ts else None
        posts.append({"post_id": m.get("code") or m.get("id"), "posted_at": posted,
                      "likes": _int(m.get("like_count")), "comments": _int(m.get("comment_count")),
                      "views": _int(m.get("play_count")), "url": m.get("url"), "image_url": m.get("display_uri")})
    return CallResult(data={"posts": posts, "next_max_id": data.get("next_max_id"),
                            "more_available": bool(data.get("more_available"))},
                      usage={"credits": _credits(data)}, cost_usd=_credits(data) * EST_COST_PER_CREDIT)


def youtube_channel_videos(*, channel_id: Optional[str] = None, handle: Optional[str] = None,
                           continuation_token: Optional[str] = None,
                           transport: Optional[httpx.BaseTransport] = None) -> CallResult:
    """One page of the channel's own upload list (2-5 YouTube 채널 성과) — not a single video lookup."""
    params: dict = {"sort": "latest"}
    if channel_id:
        params["channelId"] = channel_id
    else:
        params["handle"] = (handle or "").lstrip("@")
    if continuation_token:
        params["continuationToken"] = continuation_token
    data = _get("/youtube/channel-videos", params, transport)
    videos = []
    for v in data.get("videos") or []:
        length = _int(v.get("lengthSeconds"))
        videos.append({"id": v.get("id"), "url": v.get("url"), "title": (v.get("title") or "")[:200],
                       "views": _int(v.get("viewCountInt")), "published_at": str(v.get("publishedTime") or "")[:10] or None,
                       "length_seconds": length, "is_short": length is not None and length <= SHORTS_MAX_SECONDS})
    return CallResult(data={"videos": videos, "continuation_token": data.get("continuationToken")},
                      usage={"credits": _credits(data)}, cost_usd=_credits(data) * EST_COST_PER_CREDIT)


# ------------------------------------------------------------------ P2-6 공식 계정 6채널
# 아래 파서는 2026-11-11 실제 응답(nike)으로 필드를 확인했다 — tests/fixtures/scrapecreators/*.json이 그 응답을
# 줄인 것. 값은 모두 수집 시점의 공개 수치다.

def _paid(data: dict) -> int:
    """응답이 직접 알려 주는 차감 크레딧(credits_charged), 없으면 캐시 여부로 추정."""
    charged = data.get("credits_charged")
    return int(charged) if isinstance(charged, (int, float)) and not isinstance(charged, bool) else _credits(data)


def _result(data: dict, payload: dict) -> CallResult:
    n = _paid(data)
    return CallResult(data=payload, usage={"credits": n}, cost_usd=n * EST_COST_PER_CREDIT)


def _ts_date(ts: Any) -> Optional[str]:
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).date().isoformat() if ts else None
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _strip_query(url: Optional[str]) -> Optional[str]:
    return url.split("?", 1)[0] if url else url


def tiktok_profile(handle: str, transport: Optional[httpx.BaseTransport] = None) -> CallResult:
    """GET /v1/tiktok/profile — 팔로워·영상 수. 비공개 계정이면 SOURCE_UNAVAILABLE(접근 불가)."""
    data = _get("/tiktok/profile", {"handle": handle.lstrip("@")}, transport)
    user = data.get("user") or {}
    if not user:
        raise ProviderError("SOURCE_UNAVAILABLE", "TikTok 계정을 찾을 수 없습니다(삭제·이름 변경 가능)")
    if user.get("privateAccount") or user.get("secret"):
        raise ProviderError("SOURCE_UNAVAILABLE", "TikTok 비공개 계정이라 볼 수 없습니다")
    stats = data.get("statsV2") or data.get("stats") or {}
    return _result(data, {"followers": _int(stats.get("followerCount")), "videos": _int(stats.get("videoCount")),
                          "name": user.get("nickname") or user.get("uniqueId")})


def tiktok_profile_videos(handle: str, *, max_cursor: Optional[str] = None,
                          transport: Optional[httpx.BaseTransport] = None) -> CallResult:
    """GET /v3/tiktok/profile/videos — 최신순 한 쪽(약 10개). 고정 게시물(is_top)은 날짜순을 깨므로 표시해 둔다."""
    params = {"handle": handle.lstrip("@")}
    if max_cursor:
        params["max_cursor"] = max_cursor
    data = _get("/tiktok/profile/videos", params, transport, base=BASE_V3)
    posts = []
    for a in data.get("aweme_list") or []:
        st = a.get("statistics") or {}
        posts.append({"post_id": a.get("aweme_id"), "url": _strip_query(a.get("share_url")),
                      "posted_at": _ts_date(a.get("create_time")), "title": (a.get("desc") or "")[:200],
                      "views": _int(st.get("play_count")), "likes": _int(st.get("digg_count")),
                      "comments": _int(st.get("comment_count")), "shares": _int(st.get("share_count")),
                      "saves": _int(st.get("collect_count")), "pinned": bool(a.get("is_top"))})
    cursor = data.get("max_cursor")
    return _result(data, {"posts": posts, "cursor": str(cursor) if cursor else None, "has_more": bool(data.get("has_more"))})


def facebook_profile(url: str, transport: Optional[httpx.BaseTransport] = None) -> CallResult:
    """GET /v1/facebook/profile — 페이지 팔로워(없으면 좋아요 수)."""
    data = _get("/facebook/profile", {"url": url}, transport)
    if not data.get("id") and not data.get("name"):
        raise ProviderError("SOURCE_UNAVAILABLE", "Facebook 페이지를 찾을 수 없습니다(비공개·삭제 가능)")
    return _result(data, {"followers": _int(data.get("followerCount")) or _int(data.get("likeCount")),
                          "name": data.get("name")})


def facebook_profile_posts(url: str, *, cursor: Optional[str] = None,
                           transport: Optional[httpx.BaseTransport] = None) -> CallResult:
    """GET /v1/facebook/profile/posts — 최신순 한 쪽. reactionCount는 좋아요·최고예요 등 반응 합계."""
    params = {"url": url}
    if cursor:
        params["cursor"] = cursor
    data = _get("/facebook/profile/posts", params, transport)
    posts = []
    for p in data.get("posts") or []:
        posted = (p.get("creation_time") or "")[:10] or _ts_date(p.get("publishTime"))
        posts.append({"post_id": p.get("id"), "url": p.get("url"), "posted_at": posted, "title": (p.get("text") or "")[:200],
                      "likes": _int(p.get("reactionCount")), "comments": _int(p.get("commentCount")),
                      "shares": _int(p.get("share_count")), "views": _int(p.get("videoViewCount"))})
    return _result(data, {"posts": posts, "cursor": data.get("cursor")})


def twitter_profile(handle: str, transport: Optional[httpx.BaseTransport] = None) -> CallResult:
    """GET /v1/twitter/profile — 팔로워. 보호(비공개) 계정이면 SOURCE_UNAVAILABLE."""
    data = _get("/twitter/profile", {"handle": handle.lstrip("@")}, transport)
    legacy = data.get("legacy") or {}
    if not legacy:
        raise ProviderError("SOURCE_UNAVAILABLE", "X 계정을 찾을 수 없습니다(삭제·이름 변경 가능)")
    if legacy.get("protected"):
        raise ProviderError("SOURCE_UNAVAILABLE", "X 비공개(보호) 계정이라 볼 수 없습니다")
    return _result(data, {"followers": _int(legacy.get("followers_count")), "name": legacy.get("name")})


def twitter_user_tweets(handle: str, transport: Optional[httpx.BaseTransport] = None) -> CallResult:
    """GET /v1/twitter/user-tweets — 최신 글이 아니라 인기 글 상위 묶음이다. 게시 빈도를 만들면 안 된다."""
    data = _get("/twitter/user-tweets", {"handle": handle.lstrip("@")}, transport)
    posts = []
    for t in data.get("tweets") or []:
        lg = t.get("legacy") or {}
        posts.append({"post_id": t.get("rest_id") or lg.get("id_str"), "url": t.get("url"),
                      "posted_at": _x_date(lg.get("created_at")), "title": (lg.get("full_text") or "")[:200],
                      "likes": _int(lg.get("favorite_count")), "comments": _int(lg.get("reply_count")),
                      "shares": _int(lg.get("retweet_count")), "views": _int((t.get("views") or {}).get("count"))})
    return _result(data, {"posts": posts})


def threads_profile(handle: str, transport: Optional[httpx.BaseTransport] = None) -> CallResult:
    data = _get("/threads/profile", {"handle": handle.lstrip("@")}, transport)
    if not data.get("username"):
        raise ProviderError("SOURCE_UNAVAILABLE", "Threads 계정을 찾을 수 없습니다(삭제·이름 변경 가능)")
    if data.get("text_post_app_is_private"):
        raise ProviderError("SOURCE_UNAVAILABLE", "Threads 비공개 계정이라 볼 수 없습니다")
    return _result(data, {"followers": _int(data.get("follower_count")), "name": data.get("username")})


def threads_user_posts(handle: str, transport: Optional[httpx.BaseTransport] = None) -> CallResult:
    """GET /v1/threads/user/posts — 최근 글 한 묶음(쪽 넘김 없음, 실제로 15개)."""
    data = _get("/threads/user/posts", {"handle": handle.lstrip("@")}, transport)
    posts = []
    for t in data.get("posts") or []:
        info = t.get("text_post_app_info") or {}
        hidden = bool(t.get("like_and_view_counts_disabled"))
        posts.append({"post_id": t.get("code") or t.get("id"), "url": t.get("url"), "posted_at": _ts_date(t.get("taken_at")),
                      "title": ((t.get("caption") or {}).get("text") or "")[:200],
                      "likes": None if hidden else _int(t.get("like_count")), "comments": _int(info.get("direct_reply_count")),
                      "shares": _int(info.get("repost_count"))})
    return _result(data, {"posts": posts})


def youtube_channel_shorts(*, channel_id: Optional[str] = None, handle: Optional[str] = None,
                           continuation_token: Optional[str] = None,
                           transport: Optional[httpx.BaseTransport] = None) -> CallResult:
    """GET /v1/youtube/channel/shorts — 쇼츠 탭 한 쪽(실제로 48개). 채널 영상 목록에는 쇼츠가 일부만 섞여 나와
    쇼츠 수·조회가 적게 잡혔다(10편 문제)."""
    params: dict = {}
    if channel_id:
        params["channelId"] = channel_id
    else:
        params["handle"] = (handle or "").lstrip("@")
    if continuation_token:
        params["continuationToken"] = continuation_token
    data = _get("/youtube/channel/shorts", params, transport)
    shorts = []
    for v in data.get("shorts") or []:
        shorts.append({"id": v.get("id"), "url": v.get("url"), "title": (v.get("title") or "")[:200],
                       "views": _int(v.get("viewCountInt")), "likes": _int(v.get("likeCountInt")),
                       "comments": _int(v.get("commentCountInt")),
                       "published_at": str(v.get("publishDate") or "")[:10] or None})
    return _result(data, {"shorts": shorts, "continuation_token": data.get("continuationToken")})


# ---------------------------------------------------------------- P2-8 소비자 원문용 키워드 검색
# 필드 이름은 2026-11-11 실제 응답(샘소나이트)으로 확인했다(tests/fixtures/scrapecreators/*_search.json).

def tiktok_search_keyword(query: str, *, region: Optional[str] = "KR", cursor: Optional[str] = None,
                          transport: Optional[httpx.BaseTransport] = None) -> CallResult:
    """GET /v1/tiktok/search/keyword — 공개 영상 30개 한 쪽. region=KR이어도 해외 영상이 섞여
    오므로 한국어 여부는 부르는 쪽이 거른다. 본문은 영상 설명(desc)이다."""
    params: dict[str, Any] = {"query": query}
    if region:
        params["region"] = region
    if cursor:
        params["cursor"] = cursor
    data = _get("/tiktok/search/keyword", params, transport)
    posts = []
    for row in data.get("search_item_list") or []:
        a = row.get("aweme_info") or row
        text = (a.get("desc") or "").strip()
        url = _strip_query(a.get("url") or a.get("share_url"))
        if not text or not url:
            continue
        author = a.get("author") or {}
        st = a.get("statistics") or {}
        posts.append({"url": url, "text": text, "posted_at": _ts_date(a.get("create_time")),
                      "author": author.get("unique_id"), "followers": _int(author.get("follower_count")),
                      "views": _int(st.get("play_count")), "likes": _int(st.get("digg_count")),
                      "comments": _int(st.get("comment_count")), "region": a.get("region"),
                      "sponsored": bool(a.get("is_ad") or a.get("is_paid_partnership"))})
    cursor_out = data.get("cursor")
    return _result(data, {"posts": posts, "cursor": str(cursor_out) if cursor_out else None,
                          "has_more": bool(data.get("has_more"))})


def youtube_search(query: str, *, transport: Optional[httpx.BaseTransport] = None) -> CallResult:
    """GET /v1/youtube/search — 일반 영상과 쇼츠. 게시일(publishedTime)은 '2년 전' 같은 표시에서 나온
    근사값이고 쇼츠에는 아예 없다. 설명은 오지 않아 제목만 있다 — 댓글은 따로 부른다."""
    data = _get("/youtube/search", {"query": query}, transport)
    videos = []
    for v in [*(data.get("videos") or []), *(data.get("shorts") or [])]:
        url, title = v.get("url"), (v.get("title") or "").strip()
        if not url or not title:
            continue
        ch = v.get("channel") or {}
        videos.append({"url": url, "title": title, "posted_at": (v.get("publishedTime") or "")[:10] or None,
                       "author": ch.get("title") or ch.get("handle"), "views": _int(v.get("viewCountInt")),
                       "is_short": v.get("type") == "short"})
    return _result(data, {"videos": videos})
