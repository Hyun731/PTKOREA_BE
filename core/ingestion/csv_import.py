"""facts.csv / posts.csv ingestion (PRD 8 facts.csv, posts.csv, error handling; F01, F03).

Valid rows become candidate Facts. Nothing here makes data eligible: a person accepts the
batch (or individual cards) before calculations use it.
"""
from __future__ import annotations

import calendar
import csv
import hashlib
import io
import json
import re
from datetime import date
from typing import Iterable, Optional

from core.decimalx import DecimalParseError, canonical_decimal, parse_count, parse_decimal
from core.schemas.facts import (
    INPUT_METRICS,
    DuplicateRecord,
    Fact,
    ImportResult,
    Post,
    RowError,
)
from core.schemas.project import Project

FACT_REQUIRED = ["brand", "entity", "metric", "value", "unit", "dims", "period", "measured_at", "source", "confidence"]
FACT_OPTIONAL = ["url", "method", "source_record_key"]
POST_REQUIRED = ["post_id", "brand", "channel", "creator", "owner_type", "posted_at", "measured_at", "likes_hidden"]
POST_OPTIONAL = ["followers", "followers_measured_at", "views", "likes", "comments", "product", "url"]
POST_FIELD_METRICS = {
    "views": "post_views",
    "likes": "post_likes",
    "comments": "post_comments",
    "followers": "creator_followers",
}

WINDOW_RE = re.compile(r"^(\d{1,2})M$")
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


class RowInvalid(Exception):
    def __init__(self, column: Optional[str], code: str, message: str):
        super().__init__(message)
        self.column = column
        self.code = code
        self.message = message


def _read_rows(text: str) -> tuple[list[str], list[dict[str, str]]]:
    if text.startswith("﻿"):
        text = text[1:]
    reader = csv.DictReader(io.StringIO(text))
    rows = [dict(r) for r in reader]
    return list(reader.fieldnames or []), rows


def _parse_date(raw: str, column: str) -> date:
    try:
        return date.fromisoformat((raw or "").strip())
    except ValueError as exc:
        raise RowInvalid(column, "INVALID_DATE", f"{column} 날짜 형식(YYYY-MM-DD) 오류: {raw!r}") from exc


def parse_period(raw: str) -> tuple[date, date]:
    parts = (raw or "").split("~")
    if len(parts) != 2:
        raise RowInvalid("period", "INVALID_PERIOD", "period는 시작일~종료일 형식이어야 합니다")
    start = _parse_date(parts[0], "period")
    end = _parse_date(parts[1], "period")
    if start > end:
        raise RowInvalid("period", "INVALID_PERIOD", "period 시작일이 종료일보다 늦습니다")
    return start, end


def window_months(start: date, end: date) -> Optional[int]:
    """Number of whole calendar months covered, or None if not month-aligned."""
    if start.day != 1 or end.day != calendar.monthrange(end.year, end.month)[1]:
        return None
    return (end.year - start.year) * 12 + (end.month - start.month) + 1


def _canonical_dims(dims: dict) -> str:
    return json.dumps(dims, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_hash(payload: dict) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def fact_id_from_hash(h: str) -> str:
    return "F-" + h[:20]


def _check_header(fieldnames: list[str], required: list[str], file: str) -> list[RowError]:
    missing = [c for c in required if c not in fieldnames]
    return [RowError(file=file, row_no=1, column=c, code="MISSING_COLUMN", message=f"필수 열 {c}이 없습니다") for c in missing]


def import_facts_csv(text: str, project: Project, batch_id: str, file: str = "facts.csv") -> ImportResult:
    fieldnames, rows = _read_rows(text)
    result = ImportResult(file=file, batch_id=batch_id, total_rows=len(rows))
    header_errors = _check_header(fieldnames, FACT_REQUIRED, file)
    if header_errors:
        result.errors.extend(header_errors)
        return result

    brands = {b.id: b for b in project.brands}
    parsed: list[Fact] = []
    for idx, row in enumerate(rows):
        row_no = idx + 2  # header is row 1
        try:
            parsed.append(_parse_fact_row(row, row_no, brands, batch_id))
        except RowInvalid as err:
            result.errors.append(RowError(file=file, row_no=row_no, column=err.column, code=err.code, message=err.message))

    result.facts, result.duplicates = _dedupe(parsed)
    return result


def _parse_fact_row(row: dict, row_no: int, brands: dict, batch_id: str) -> Fact:
    def cell(name: str) -> str:
        return (row.get(name) or "").strip()

    brand_id = cell("brand")
    if brand_id not in brands:
        raise RowInvalid("brand", "UNKNOWN_BRAND", f"프로젝트에 없는 brand {brand_id!r}")
    brand = brands[brand_id]
    entity = cell("entity")
    if entity not in brand.entity_set:
        # Benchmarks and unknown names never enter share denominators.
        raise RowInvalid("entity", "UNKNOWN_ENTITY", f"{brand.name} 경쟁 세트에 없는 entity {entity!r}")
    metric = cell("metric")
    if metric not in INPUT_METRICS:
        raise RowInvalid("metric", "UNKNOWN_METRIC", f"정의되지 않은 metric {metric!r}")
    unit_expected, required_dims, optional_dims = INPUT_METRICS[metric]
    unit = cell("unit")
    if unit != unit_expected:
        raise RowInvalid("unit", "INVALID_UNIT", f"{metric}의 unit은 {unit_expected}이어야 합니다")
    try:
        dims = json.loads(cell("dims") or "{}")
    except json.JSONDecodeError as exc:
        raise RowInvalid("dims", "INVALID_DIMS", "dims JSON 파싱 실패") from exc
    if not isinstance(dims, dict) or not all(isinstance(v, str) for v in dims.values()):
        raise RowInvalid("dims", "INVALID_DIMS", "dims는 문자열 값의 객체여야 합니다")
    missing = required_dims - dims.keys()
    if missing:
        raise RowInvalid("dims", "INVALID_DIMS", f"dims 필수 키 누락: {', '.join(sorted(missing))}")
    extra = dims.keys() - required_dims - optional_dims
    if extra:
        raise RowInvalid("dims", "INVALID_DIMS", f"허용되지 않은 dims 키: {', '.join(sorted(extra))}")
    if dims["seg"] not in ("all", "T"):
        raise RowInvalid("dims", "INVALID_DIMS", "seg는 all 또는 T여야 합니다")
    if "cat" in dims and not dims["cat"].strip():
        raise RowInvalid("dims", "INVALID_DIMS", "cat이 비어 있습니다")

    start, end = parse_period(cell("period"))
    if metric == "search_group_sum":
        m = WINDOW_RE.match(dims["window"])
        if not m:
            raise RowInvalid("dims", "INVALID_WINDOW", f"window 라벨 형식 오류 {dims['window']!r}")
        months = window_months(start, end)
        if months is None or months != int(m.group(1)):
            raise RowInvalid("period", "WINDOW_MISMATCH", f"window {dims['window']}와 실제 기간 {start}~{end}의 길이가 다릅니다")
    else:
        if not MONTH_RE.match(dims["month"]):
            raise RowInvalid("dims", "INVALID_DIMS", "month는 YYYY-MM 형식이어야 합니다")
        y, mo = map(int, dims["month"].split("-"))
        if not (start <= date(y, mo, 1) <= end):
            raise RowInvalid("dims", "MONTH_OUT_OF_PERIOD", "month가 period 밖입니다")

    measured_at = _parse_date(cell("measured_at"), "measured_at")
    confidence = cell("confidence")
    if confidence not in ("verified", "estimated", "missing"):
        raise RowInvalid("confidence", "INVALID_CONFIDENCE", "confidence는 verified/estimated/missing 중 하나")
    try:
        value = parse_decimal(cell("value"))
    except DecimalParseError as exc:
        raise RowInvalid("value", "INVALID_VALUE", str(exc)) from exc
    if confidence == "missing":
        if value is not None:
            raise RowInvalid("value", "INVALID_VALUE", "missing 행의 value는 비어 있어야 합니다")
    else:
        if value is None:
            raise RowInvalid("value", "INVALID_VALUE", "value가 비어 있습니다. 결측이면 confidence=missing")
        if value < 0:
            raise RowInvalid("value", "INVALID_VALUE", "지수는 음수일 수 없습니다")
    source = cell("source")
    if not source:
        raise RowInvalid("source", "MISSING_SOURCE", "source가 비어 있습니다")

    record_key = cell("source_record_key") or None
    payload = {
        "brand": brand_id, "entity": entity, "metric": metric, "value": canonical_decimal(value),
        "unit": unit, "dims": _canonical_dims(dims), "period": f"{start}~{end}",
        "measured_at": measured_at.isoformat(), "source": source, "url": cell("url") or None,
        "method": cell("method") or None, "confidence": confidence, "source_record_key": record_key,
    }
    h = content_hash(payload)
    return Fact(
        id=fact_id_from_hash(h), content_hash=h, brand_id=brand_id, entity=entity, metric=metric,
        value=value, unit=unit, dims=dims, period_start=start, period_end=end, measured_at=measured_at,
        source=source, url=cell("url") or None, method=cell("method") or None, confidence=confidence,
        source_record_key=record_key, batch_id=batch_id, row_no=row_no,
    )


def natural_key(f: Fact) -> str:
    return "|".join([f.brand_id, f.entity, f.metric, _canonical_dims(f.dims), f"{f.period_start}~{f.period_end}"])


def _dedupe(facts: Iterable[Fact]) -> tuple[list[Fact], list[DuplicateRecord]]:
    """Same natural key: latest measured_at wins, ties -> later CSV row (PRD 8).

    Different sources with different values are a provider conflict: keep all candidates
    and mark them so the metric is held until a person picks one.
    """
    groups: dict[str, list[Fact]] = {}
    seen_ids: set[str] = set()
    duplicates: list[DuplicateRecord] = []
    for f in facts:
        if f.id in seen_ids:
            duplicates.append(DuplicateRecord(kept_row=f.row_no or 0, dropped_row=f.row_no or 0,
                                              natural_key=natural_key(f), reason="identical_row"))
            continue
        seen_ids.add(f.id)
        groups.setdefault(natural_key(f), []).append(f)

    kept: list[Fact] = []
    for key, members in groups.items():
        if len(members) == 1:
            kept.append(members[0])
            continue
        sources = {m.source for m in members}
        values = {canonical_decimal(m.value) for m in members}
        if len(sources) > 1 and len(values) > 1:
            for m in members:
                kept.append(m.model_copy(update={"conflict_key": key}))
            continue
        winner = max(members, key=lambda m: (m.measured_at, m.row_no or 0))
        kept.append(winner)
        for m in members:
            if m is not winner:
                duplicates.append(DuplicateRecord(kept_row=winner.row_no or 0, dropped_row=m.row_no or 0,
                                                  natural_key=key, reason="superseded"))
    kept.sort(key=lambda f: f.row_no or 0)
    return kept, duplicates


def _parse_bool(raw: str, column: str) -> bool:
    v = (raw or "").strip().lower()
    if v in ("true", "1", "yes", "y"):
        return True
    if v in ("false", "0", "no", "n"):
        return False
    raise RowInvalid(column, "INVALID_BOOL", f"{column}는 true/false여야 합니다")


def import_posts_csv(text: str, project: Project, batch_id: str, file: str = "posts.csv",
                     source_name: str = "posts.csv") -> ImportResult:
    fieldnames, rows = _read_rows(text)
    result = ImportResult(file=file, batch_id=batch_id, total_rows=len(rows))
    header_errors = _check_header(fieldnames, POST_REQUIRED, file)
    if "quarter" in fieldnames:
        header_errors.append(RowError(file=file, row_no=1, column="quarter", code="DERIVED_COLUMN",
                                      message="quarter는 posted_at으로 계산하므로 입력하지 않습니다"))
    if header_errors:
        result.errors.extend(header_errors)
        return result
    brand_ids = {b.id for b in project.brands}
    seen_posts: set[tuple[str, str]] = set()
    for idx, row in enumerate(rows):
        row_no = idx + 2
        try:
            post, facts = _parse_post_row(row, row_no, brand_ids, batch_id, source_name)
        except RowInvalid as err:
            result.errors.append(RowError(file=file, row_no=row_no, column=err.column, code=err.code, message=err.message))
            continue
        key = (post.brand_id, post.post_id)
        if key in seen_posts:
            result.errors.append(RowError(file=file, row_no=row_no, column="post_id", code="DUPLICATE_POST",
                                          message=f"post_id {post.post_id} 중복"))
            continue
        seen_posts.add(key)
        result.posts.append(post)
        result.facts.extend(facts)
    return result


def _parse_post_row(row: dict, row_no: int, brand_ids: set[str], batch_id: str,
                    source_name: str = "posts.csv") -> tuple[Post, list[Fact]]:
    def cell(name: str) -> str:
        return (row.get(name) or "").strip()

    if not cell("post_id"):
        raise RowInvalid("post_id", "MISSING_VALUE", "post_id가 비어 있습니다")
    if cell("brand") not in brand_ids:
        raise RowInvalid("brand", "UNKNOWN_BRAND", f"프로젝트에 없는 brand {cell('brand')!r}")
    channel = cell("channel")
    if channel not in ("youtube", "instagram"):
        raise RowInvalid("channel", "INVALID_CHANNEL", "channel은 youtube/instagram")
    owner = cell("owner_type")
    if owner not in ("self", "co", "creator"):
        raise RowInvalid("owner_type", "INVALID_OWNER", "owner_type은 self/co/creator")
    if not cell("creator"):
        raise RowInvalid("creator", "MISSING_VALUE", "creator가 비어 있습니다")
    posted_at = _parse_date(cell("posted_at"), "posted_at")
    measured_at = _parse_date(cell("measured_at"), "measured_at")
    counts: dict[str, Optional[int]] = {}
    for name in ("followers", "views", "likes", "comments"):
        try:
            counts[name] = parse_count(cell(name))
        except DecimalParseError as exc:
            raise RowInvalid(name, "INVALID_COUNT", f"{name}: {exc}") from exc
    followers_measured_at = None
    if counts["followers"] is not None:
        if not cell("followers_measured_at"):
            raise RowInvalid("followers_measured_at", "MISSING_VALUE", "followers가 있으면 followers_measured_at이 필요합니다")
        followers_measured_at = _parse_date(cell("followers_measured_at"), "followers_measured_at")
    likes_hidden = _parse_bool(cell("likes_hidden"), "likes_hidden")
    if likes_hidden and counts["likes"] is not None:
        raise RowInvalid("likes", "INVALID_COUNT", "likes_hidden=true인데 likes 값이 있습니다")

    post = Post(
        post_id=cell("post_id"), brand_id=cell("brand"), channel=channel, creator=cell("creator"),
        owner_type=owner, posted_at=posted_at, measured_at=measured_at, followers=counts["followers"],
        followers_measured_at=followers_measured_at, views=counts["views"], likes=counts["likes"],
        comments=counts["comments"], likes_hidden=likes_hidden, product=cell("product") or None,
        url=cell("url") or None, row_no=row_no, batch_id=batch_id,
    )
    facts: list[Fact] = []
    for field, metric in POST_FIELD_METRICS.items():
        value = counts[field]
        if value is None:
            continue  # null stays null: no Fact, never 0
        observed = followers_measured_at if field == "followers" else measured_at
        dims = {"post_id": post.post_id, "channel": channel}
        if field == "followers":
            dims["rate_basis"] = post.rate_basis
        payload = {
            "brand": post.brand_id, "entity": post.creator, "metric": metric, "value": str(value),
            "dims": _canonical_dims(dims), "posted_at": posted_at.isoformat(),
            "measured_at": observed.isoformat(), "source": source_name, "url": post.url,
            "source_record_key": f"{post.post_id}:{field}",
        }
        h = content_hash(payload)
        fact = Fact(
            id=fact_id_from_hash(h), content_hash=h, brand_id=post.brand_id, entity=post.creator,
            metric=metric, value=value, unit="count", dims=dims, period_start=posted_at,
            period_end=posted_at, measured_at=observed, source=source_name, url=post.url,
            confidence="verified", source_record_key=f"{post.post_id}:{field}",
            source_locator=f"{post.post_id}:{field}", batch_id=batch_id, row_no=row_no,
        )
        facts.append(fact)
        post.fact_ids[field] = fact.id
    return post, facts
