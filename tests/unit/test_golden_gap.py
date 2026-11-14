import json
from pathlib import Path

from core.golden_baseline import load_golden_baseline
from core.golden_gap import evaluate_golden_gap
from tools.evaluate_golden_gap import main

FIXTURE = Path(__file__).parents[1] / "fixtures" / "golden_baseline"


def outline():
    return {
        "pages": 3,
        "missing": [{"slot_id": "missing"}],
        "flow": [
            {"kind": "section", "title": "Brand Alpha"},
            {"kind": "slide", "page_no": 2, "section": "Alpha", "title": "Category demand increased",
             "lead": "Category demand increased by 12 percent", "evidence": [], "points": []},
            {"kind": "slide", "page_no": 3, "section": "Other", "title": "Unassigned", "lead": "", "points": []},
        ],
    }


def test_evaluates_brand_and_claim_coverage():
    result = evaluate_golden_gap(load_golden_baseline(FIXTURE, strict=True), outline(),
                                 aliases={"Brand Alpha": ["Alpha"]}, similarity_threshold=0.05)
    assert result["outline_slides"] == 2
    assert result["missing_slots"] == 1
    assert result["brands"]["Brand Alpha"]["actual_slides"] == 1
    assert result["brands"]["Brand Alpha"]["matched_claims"] >= 1
    assert result["unassigned_slides"] == [{"page_no": 3, "title": "Unassigned"}]


def test_cli_writes_json(tmp_path, capsys):
    path = tmp_path / "outline.json"
    path.write_text(json.dumps(outline()))
    assert main([str(FIXTURE), str(path), "--brand-alias", "Brand Alpha=Alpha"]) == 0
    assert json.loads(capsys.readouterr().out)["baseline_id"] == "synthetic-luggage-2026-v1"
