from __future__ import annotations

import argparse
import json

from core.golden_baseline import load_golden_baseline
from core.golden_gap import evaluate_golden_gap


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Compare an outline JSON response with a private golden baseline")
    parser.add_argument("baseline")
    parser.add_argument("outline")
    parser.add_argument("--brand-alias", action="append", default=[], metavar="BRAND=ALIAS")
    parser.add_argument("--threshold", type=float, default=0.05)
    args = parser.parse_args(argv)
    aliases: dict[str, list[str]] = {}
    for item in args.brand_alias:
        brand, separator, alias = item.partition("=")
        if not separator or not brand.strip() or not alias.strip():
            parser.error("--brand-alias must use BRAND=ALIAS")
        aliases.setdefault(brand.strip(), []).append(alias.strip())
    baseline = load_golden_baseline(args.baseline, strict=True)
    with open(args.outline, encoding="utf-8") as stream:
        outline = json.load(stream)
    print(json.dumps(evaluate_golden_gap(baseline, outline, aliases=aliases,
                                         similarity_threshold=args.threshold), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
