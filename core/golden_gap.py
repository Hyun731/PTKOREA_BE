"""Compare a generated outline with a validated golden baseline."""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from core.golden_baseline import GoldenBaseline


def _normalized(text: str) -> str:
    return re.sub(r"[^0-9a-z가-힣]+", "", text.lower())


def _grams(text: str, size: int = 3) -> set[str]:
    value = _normalized(text)
    return {value[index:index + size] for index in range(max(0, len(value) - size + 1))}


def _similarity(left: str, right: str) -> float:
    left_grams, right_grams = _grams(left), _grams(right)
    if not left_grams or not right_grams:
        return 0.0
    return len(left_grams & right_grams) / len(left_grams | right_grams)


def _slide_text(slide: dict[str, Any]) -> str:
    values = [slide.get("section", ""), slide.get("title", ""), slide.get("lead", "")]
    values.extend(slide.get("evidence", []))
    values.extend(slide.get("points", []))
    return " ".join(str(value) for value in values if value)


def evaluate_golden_gap(
    baseline: GoldenBaseline,
    outline: dict[str, Any],
    *,
    aliases: dict[str, list[str]] | None = None,
    similarity_threshold: float = 0.05,
) -> dict[str, Any]:
    """Measure balanced brand coverage and lexical claim coverage for an outline response."""
    aliases = aliases or {}
    actual = [item for item in outline.get("flow", [])
              if item.get("kind") == "slide" and item.get("page_role", "content") in {"content", "recap"}]
    by_brand: dict[str, list[tuple[dict[str, Any], str]]] = defaultdict(list)
    unassigned: list[dict[str, Any]] = []
    names = {brand: [brand, *aliases.get(brand, [])] for brand in baseline.manifest.brands}

    for slide in actual:
        text = _slide_text(slide)
        normalized_text = _normalized(text)
        matches = [(len(_normalized(candidate)), brand) for brand, candidates in names.items() for candidate in candidates
                   if _normalized(candidate) and _normalized(candidate) in normalized_text]
        best = max((length for length, _ in matches), default=0)
        brands = {brand for length, brand in matches if length == best}
        if len(brands) == 1:
            by_brand[brands.pop()].append((slide, text))
        else:
            unassigned.append({"page_no": slide.get("page_no"), "title": slide.get("title", "")})

    expected_pages = defaultdict(int)
    for slide in baseline.slides:
        if slide.brand in names and slide.fact_status == "complete" and slide.claim_status == "complete":
            expected_pages[slide.brand] += 1

    brand_reports: dict[str, Any] = {}
    for brand in baseline.manifest.brands:
        brand_claims = [claim for claim in baseline.claims if claim.brand == brand]
        generated = by_brand[brand]
        matches = []
        for claim in brand_claims:
            scored = [(_similarity(claim.text, text), slide.get("page_no"), slide.get("title", ""))
                      for slide, text in generated]
            score, page_no, title = max(scored, default=(0.0, None, ""))
            matches.append({"claim_id": claim.claim_id, "score": round(score, 4), "page_no": page_no,
                            "title": title, "claim": claim.text})
        expected = expected_pages[brand]
        matched = sum(item["score"] >= similarity_threshold for item in matches)
        brand_reports[brand] = {
            "expected_pages": expected,
            "actual_slides": len(generated),
            "page_coverage": round(min(1.0, len(generated) / expected), 4) if expected else 1.0,
            "claims": len(brand_claims),
            "matched_claims": matched,
            "claim_coverage": round(matched / len(matches), 4) if matches else 1.0,
            "mean_max_similarity": round(sum(item["score"] for item in matches) / len(matches), 4) if matches else 0.0,
            "worst_unmatched": sorted(matches, key=lambda item: item["score"])[:10],
        }

    reports = list(brand_reports.values())
    return {
        "baseline_id": baseline.manifest.baseline_id,
        "outline_pages": outline.get("pages"),
        "outline_slides": len(actual),
        "missing_slots": len(outline.get("missing", [])),
        "similarity_threshold": similarity_threshold,
        "balanced_page_coverage": round(sum(item["page_coverage"] for item in reports) / len(reports), 4),
        "balanced_claim_coverage": round(sum(item["claim_coverage"] for item in reports) / len(reports), 4),
        "brands": brand_reports,
        "unassigned_slides": unassigned,
    }
