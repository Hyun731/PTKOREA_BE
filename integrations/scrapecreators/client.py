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
                      "views": _int(m.get("play_count")), "url": m.get("url")})
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
