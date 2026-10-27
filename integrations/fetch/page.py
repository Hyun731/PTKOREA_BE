"""Fetch public pages and images safely (PRD 14 URL 수집 보안).

http/https only; every hop of a redirect is re-checked; loopback, private, link-local,
reserved and metadata addresses are refused; size and time are capped. Page text is data,
never instructions (PRD 7).
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import socket
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Callable, Optional
from urllib.parse import urljoin, urlparse

import httpx

from integrations.base import ProviderError

MAX_PAGE_BYTES = 3 * 1024 * 1024
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_TEXT_CHARS = 40_000
USER_AGENT = "Mozilla/5.0 (compatible; PTK-ResearchBot/0.1; +https://example.invalid/bot)"

Resolver = Callable[[str], list[str]]


def _default_resolver(host: str) -> list[str]:
    return [info[4][0] for info in socket.getaddrinfo(host, None)]


def check_url(url: str, resolve: Resolver = _default_resolver) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ProviderError("BLOCKED_URL", "http/https 공개 주소만 가져올 수 있습니다")
    host = parsed.hostname
    if host in ("localhost",) or host.endswith((".localhost", ".local", ".internal")):
        raise ProviderError("BLOCKED_URL", "내부 주소는 가져오지 않습니다")
    try:
        addrs = resolve(host)
    except OSError:
        raise ProviderError("SOURCE_UNAVAILABLE", "주소를 찾을 수 없습니다")
    for a in addrs:
        ip = ipaddress.ip_address(a.split("%")[0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast
                or ip.is_unspecified or str(ip).startswith("169.254.")):
            raise ProviderError("BLOCKED_URL", "내부·예약 주소로 연결되는 URL은 가져오지 않습니다")
    return url


def _get(url: str, *, accept: str, max_bytes: int, resolve: Resolver,
         transport: Optional[httpx.BaseTransport]) -> tuple[str, str, bytes]:
    """GET following up to 5 redirects manually. Returns (final_url, content_type, body)."""
    current = url
    with httpx.Client(timeout=15.0, follow_redirects=False, transport=transport,
                      headers={"User-Agent": USER_AGENT, "Accept": accept}) as client:
        for _ in range(6):
            check_url(current, resolve)
            try:
                with client.stream("GET", current) as resp:
                    if resp.status_code in (301, 302, 303, 307, 308) and resp.headers.get("location"):
                        current = urljoin(current, resp.headers["location"])
                        continue
                    if resp.status_code >= 400:
                        raise ProviderError("SOURCE_UNAVAILABLE", f"원문 접근 실패 ({resp.status_code})", resp.status_code)
                    body = b""
                    for chunk in resp.iter_bytes():
                        body += chunk
                        if len(body) > max_bytes:
                            raise ProviderError("SOURCE_UNAVAILABLE", "원문이 너무 큽니다")
                    return current, resp.headers.get("content-type", ""), body
            except httpx.TimeoutException:
                raise ProviderError("TIMEOUT", "원문 응답 시간 초과")
            except httpx.HTTPError as exc:
                raise ProviderError("SOURCE_UNAVAILABLE", f"원문 연결 실패: {type(exc).__name__}")
    raise ProviderError("SOURCE_UNAVAILABLE", "리다이렉트가 너무 많습니다")


BORING_IMAGE = re.compile(r"logo|icon|btn|button|banner_top|sprite|blank|spacer|quick_img|coupon|\.svg|\.gif", re.I)


class _TextExtractor(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "header", "form", "iframe"}
    BLOCK = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "tr", "section", "article"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth_skip = 0
        self.parts: list[str] = []
        self.meta: dict[str, str] = {}
        self.title = ""
        self._in_title = False
        self.ld_json: list[str] = []
        self._in_ld = False
        self.body_images: list[str] = []  # in-content <img>, outside nav/header/footer

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "meta":
            key = (a.get("property") or a.get("name") or a.get("itemprop") or "").lower()
            if key and a.get("content"):
                self.meta.setdefault(key, a["content"])
        if tag == "script" and (a.get("type") or "").lower() == "application/ld+json":
            self._in_ld = True
        if tag == "img" and not self.depth_skip:
            src = a.get("data-src") or a.get("src") or ""
            if src and not src.startswith("data:") and not BORING_IMAGE.search(src):
                self.body_images.append(src)
        if tag in self.SKIP:
            self.depth_skip += 1
        if tag == "title":
            self._in_title = True
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.depth_skip:
            self.depth_skip -= 1
        if tag == "title":
            self._in_title = False
        if tag == "script":
            self._in_ld = False

    def handle_data(self, data):
        if self._in_ld:
            self.ld_json.append(data)
            return
        if self._in_title:
            self.title += data
        if not self.depth_skip:
            self.parts.append(data)


@dataclass
class Page:
    url: str
    final_url: str
    title: str
    text: str
    content_hash: str
    published: Optional[str] = None  # YYYY-MM-DD when the page states it
    publisher: Optional[str] = None
    image_urls: list[str] = field(default_factory=list)


DATE_RE = re.compile(r"(20\d{2})[-./](\d{1,2})[-./](\d{1,2})")


def _date(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    m = DATE_RE.search(value)
    if not m:
        return None
    y, mo, d = (int(x) for x in m.groups())
    if not (1 <= mo <= 12 and 1 <= d <= 31):
        return None
    return f"{y:04d}-{mo:02d}-{d:02d}"


def _decode(body: bytes, ctype: str) -> str:
    """Header charset, else <meta charset>, else UTF-8 with an EUC-KR fallback (older Korean news sites)."""
    m = re.search(r"charset=[\"']?([\w-]+)", ctype) or re.search(rb"<meta[^>]+charset=[\"']?([\w-]+)", body[:4096], re.I)
    names = [m.group(1).decode() if isinstance(m.group(1), bytes) else m.group(1)] if m else []
    for name in [*names, "utf-8", "cp949"]:
        try:
            return body.decode({"euc-kr": "cp949", "ks_c_5601-1987": "cp949"}.get(name.lower(), name))
        except (LookupError, UnicodeDecodeError):
            continue
    return body.decode("utf-8", errors="replace")


def fetch_page(url: str, *, resolve: Resolver = _default_resolver,
               transport: Optional[httpx.BaseTransport] = None) -> Page:
    final_url, ctype, body = _get(url, accept="text/html,application/xhtml+xml", max_bytes=MAX_PAGE_BYTES,
                                  resolve=resolve, transport=transport)
    if "html" not in ctype and "text" not in ctype:
        raise ProviderError("SOURCE_UNAVAILABLE", f"HTML 문서가 아닙니다 ({ctype or '형식 불명'})")
    html = _decode(body, ctype)
    p = _TextExtractor()
    p.feed(html)
    text = re.sub(r"[ \t\r\f\v]+", " ", "".join(p.parts))
    text = re.sub(r"\n\s*\n+", "\n", text).strip()[:MAX_TEXT_CHARS]
    published = None
    for key in ("article:published_time", "og:published_time", "datepublished", "pubdate", "date"):
        published = published or _date(p.meta.get(key))
    for blob in p.ld_json:
        if published:
            break
        try:
            data = json.loads(blob)
        except ValueError:
            continue
        items = data if isinstance(data, list) else [data]
        for it in items:
            if isinstance(it, dict):
                published = published or _date(str(it.get("datePublished") or ""))
    images = []
    for key in ("og:image", "og:image:url", "twitter:image"):
        if p.meta.get(key):
            images.append(urljoin(final_url, p.meta[key]))
    # Brand sites often reuse one banner as og:image on every post; keep content images as alternatives.
    images += [urljoin(final_url, src) for src in p.body_images[:3]]
    title = (p.meta.get("og:title") or p.title or "").strip()[:300]
    publisher = (p.meta.get("og:site_name") or "").strip()[:120] or None
    return Page(url=url, final_url=final_url, title=title, text=text,
                content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(), published=published,
                publisher=publisher, image_urls=list(dict.fromkeys(images)))


def fetch_image(url: str, *, resolve: Resolver = _default_resolver,
                transport: Optional[httpx.BaseTransport] = None) -> bytes:
    _, ctype, body = _get(url, accept="image/png,image/jpeg,image/webp", max_bytes=MAX_IMAGE_BYTES,
                          resolve=resolve, transport=transport)
    if not ctype.startswith("image/"):
        raise ProviderError("SOURCE_UNAVAILABLE", "이미지가 아닙니다")
    return body
