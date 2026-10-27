"""Batch acceptance: a person adopts an import batch before calculations use it (PRD 8)."""
from __future__ import annotations

from core.schemas.facts import Fact, ImportResult, Post


def accept_facts(facts: list[Fact]) -> list[Fact]:
    return [f.model_copy(update={"verification_status": "eligible"}) for f in facts]


def accept_posts(posts: list[Post]) -> list[Post]:
    return [p.model_copy(update={"verification_status": "eligible"}) for p in posts]


def accept_batch(result: ImportResult) -> ImportResult:
    return result.model_copy(update={"facts": accept_facts(result.facts), "posts": accept_posts(result.posts)})
