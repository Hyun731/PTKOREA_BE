"""Style tokens loader. Same JSON is served to the web preview (single source)."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from core.schemas.slidespec import Region

ROOT = Path(__file__).resolve().parents[2]
TOKENS_PATH = ROOT / "templates" / "style_tokens.v1.json"
FONTS_DIR = ROOT / "templates" / "fonts"


@lru_cache(maxsize=1)
def tokens() -> dict:
    return json.loads(TOKENS_PATH.read_text(encoding="utf-8"))


def color(role: str) -> str:
    """Token role -> RRGGBB. Editor edits may also store a literal '#RRGGBB'."""
    if role.startswith("#"):
        return role[1:]
    return tokens()["colors"].get(role, role)


def region(name: str) -> Region:
    return Region(**tokens()["regions"][name])


def type_spec(name: str) -> dict:
    return tokens()["type"][name]


def weight_info(weight) -> dict:
    """Weight name (or legacy bool) -> {family, bold, file} from the style tokens."""
    if weight is True:
        weight = "bold"
    elif weight in (False, None):
        weight = "regular"
    return tokens()["font"]["weights"][weight]


def resolve_weight(part_weight=None, part_bold=False, para_weight=None, para_bold=False, block_weight=None,
                   block_bold=False) -> str:
    """Most specific wins: an explicit weight, then bold flags, then the block's weight."""
    if part_weight:
        return part_weight
    if part_bold:
        return "bold"
    if para_weight:
        return para_weight
    if para_bold or block_bold:
        return "bold"
    return block_weight or "regular"
