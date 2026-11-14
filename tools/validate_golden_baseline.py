from __future__ import annotations

import argparse
import json
import sys

from core.golden_baseline import GoldenBaselineError, load_golden_baseline


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Validate a private golden baseline directory")
    parser.add_argument("directory")
    parser.add_argument("--strict", action="store_true", help="fail when any record still needs review")
    args = parser.parse_args(argv)
    try:
        baseline = load_golden_baseline(args.directory, strict=args.strict)
    except (OSError, GoldenBaselineError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps({
        "baseline_id": baseline.manifest.baseline_id,
        "slides": len(baseline.slides),
        "facts": len(baseline.facts),
        "claims": len(baseline.claims),
        "strict": args.strict,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
