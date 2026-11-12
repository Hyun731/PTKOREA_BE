"""P4-4 5-3 구매 여정 · 5-4 구매 상황 지도: 종합 AI 답을 근거 장표·원문 인용으로 거른다."""
from tests.helpers import load_fixture


def test_synthesis_cleaners_keep_cited_stages_and_verbatim_reasons():
    from app.services import synthesis as svc
    pages = {"BL1": {"sources": ["https://example.com/bl1"]}, "PP1": {}}
    journey, issues = svc._clean_journey({"journey_lead": "가격에서 멈추는 여정", "stages": [
        {"stage": "탐색", "touchpoint": "블로그 후기", "state": "후기 비교", "drop": "", "ref": "BL1"},
        {"stage": "구매", "touchpoint": "공식몰", "state": "할인 대기", "drop": "가격 부담", "ref": "PP1"},
        {"stage": "재구매", "touchpoint": "매장", "state": "3년 사용", "drop": "", "ref": "PP1"},
        {"stage": "비교", "touchpoint": "쇼핑 검색", "state": "가격 비교", "drop": "", "ref": "X9"}]}, pages, set())
    assert [s["stage"] for s in journey["stages"]] == ["탐색", "구매"] and len(issues) == 2  # a digit, an unknown page
    assert journey["stages"][0]["source_url"] == "https://example.com/bl1"

    project, _, _ = load_fixture()
    voc = [{"text": "튼튼해서 오래 쓴다는 후기가 많아요", "url": "https://example.com/V1", "site": "카페", "date": "2026-05-01"},
           {"text": "가격이 너무 높다 싶어요", "url": "https://example.com/V2", "site": "지식iN", "date": "2026-06-02"}]
    out, issues = svc._clean_situation({"situation_lead": "", "situations": [
        {"situation": "첫 해외여행", "brands": ["브랜드A", "경쟁X", "브랜드B", "모르는곳"],
         "pick_quote": "튼튼해서 오래 쓴다", "skip_quote": "가격이 너무 높다"},
        {"situation": "출장", "brands": ["경쟁Y"], "pick_quote": "지어낸 문장", "skip_quote": ""}]},
        {}, set(), voc=voc, brand=project.brands[0], self_names=frozenset({"브랜드A", "브랜드B"}))
    assert len(out["rows"]) == 1 and len(issues) == 1  # a quote that is not in the posts is dropped
    row = out["rows"][0]
    assert row["brands"] == ["브랜드A", "경쟁X"]  # no second self brand, no unknown name
    assert row["pick"]["url"] == "https://example.com/V1" and row["skip"]["site"] == "지식iN"
