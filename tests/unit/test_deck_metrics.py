"""P1-3 덱 측정 도구 (tools/deck_metrics.py)."""
import json

from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.enum.chart import XL_CHART_TYPE
from pptx.util import Emu

from tools.deck_metrics import main, measure

W, H = 12192000, 6858000


def _deck():
    prs = Presentation()
    prs.slide_width, prs.slide_height = Emu(W), Emu(H)
    return prs


def _box(slide, name, text, top, height=0.05, left=0.04, width=0.9):
    tb = slide.shapes.add_textbox(Emu(int(W * left)), Emu(int(H * top)), Emu(int(W * width)), Emu(int(H * height)))
    tb.name = name
    tf = tb.text_frame
    lines = text.split("\n")
    tf.text = lines[0]
    for line in lines[1:]:
        tf.add_paragraph().text = line
    return tb


def _filler(slide, top, bottom, text="본문 내용 " * 50):  # 본문으로 볼 만큼(150자+) 글을 채움
    _box(slide, "body", text, top, bottom - top)


def test_our_deck_uses_shape_names(tmp_path):
    prs = _deck()
    s = prs.slides.add_slide(prs.slide_layouts[6])
    _box(s, "title", "자사 채널 · 비교", 0.03)
    _box(s, "lead_claim", "검색은 2위인데 판매는 10위", 0.08)
    _box(s, "lead_evidence", "- 무신사 40세+ 판매 10위 · 검색 점유 37.0%", 0.13)
    _filler(s, 0.25, 0.45)  # 아래가 비어 있음
    _box(s, "insight0_title", "검색 이탈", 0.80, width=0.3)
    _box(s, "insight1_title", "리뷰 부족", 0.80, left=0.35, width=0.3)
    _box(s, "footnote", "*출처 테스트", 0.93)
    prs.save(tmp_path / "ours.pptx")
    m = measure(tmp_path / "ours.pptx").per_slide[0]
    assert m.body and m.headline_ok and m.insights_ok
    # 인사이트가 바닥까지 채우므로 비지 않음
    assert m.bottom_empty < 0.35


def test_bottom_empty_slide_is_flagged(tmp_path):
    prs = _deck()
    s = prs.slides.add_slide(prs.slide_layouts[6])
    _box(s, "title", "제목", 0.03)
    _box(s, "lead", "설명하는 문장만 있는 헤드라인", 0.08)
    _filler(s, 0.25, 0.40)
    _box(s, "footnote", "*출처", 0.93)
    prs.save(tmp_path / "thin.pptx")
    d = measure(tmp_path / "thin.pptx")
    m = d.per_slide[0]
    assert not m.headline_ok and not m.insights_ok
    assert m.bottom_empty > 0.6
    assert d.empty_slides == [1] and d.headline_rate == 0.0


def test_external_deck_layout_heuristics(tmp_path):
    prs = _deck()
    s = prs.slides.add_slide(prs.slide_layouts[6])
    _box(s, "Headline", "러기지 인지·신뢰는 확고한 1위", 0.12)
    _box(s, "SubBullets", "- 러기지 고려 61%로 단독 1위\n- '1황 브랜드의 신뢰감'이 선택 이유", 0.18, 0.1)
    _filler(s, 0.32, 0.78)
    for i, x in enumerate((0.04, 0.35, 0.66)):
        _box(s, f"TextBox {i}", str(i + 1), 0.80, width=0.03, left=x)
        _box(s, f"TextBox t{i}", "기능이 아닌 감성으로 확장", 0.80, left=x + 0.03, width=0.27)
    _box(s, "Footer", "출처  테스트", 0.94)
    d = prs.slides.add_slide(prs.slide_layouts[6])  # 간지: 본문에서 빠짐
    _box(d, "DivTitle", "PART Ⅰ " + "간지 설명 " * 40, 0.1)
    prs.save(tmp_path / "ref.pptx")
    deck = measure(tmp_path / "ref.pptx")
    m = deck.per_slide[0]
    assert m.headline_ok and m.insights_ok and m.bottom_empty < 0.35
    assert deck.body_slides == 1 and not deck.per_slide[1].body


def test_counts_charts_tables_and_numbers(tmp_path):
    prs = _deck()
    s = prs.slides.add_slide(prs.slide_layouts[6])
    _filler(s, 0.05, 0.2, "본문 " * 80)
    data = CategoryChartData()
    data.categories = ["a", "b"]
    data.add_series("s", (1, 2))
    s.shapes.add_chart(XL_CHART_TYPE.COLUMN_STACKED, 0, Emu(int(H * 0.3)), Emu(W // 2), Emu(H // 3), data)
    tbl = s.shapes.add_table(2, 2, Emu(W // 2), Emu(int(H * 0.3)), Emu(W // 3), Emu(H // 4)).table
    tbl.cell(0, 0).text, tbl.cell(1, 1).text = "61%", "1,234"
    prs.save(tmp_path / "c.pptx")
    d = measure(tmp_path / "c.pptx")
    assert d.charts == 1 and d.chart_kinds == {"COLUMN_STACKED": 1} and d.tables == 1
    assert d.per_slide[0].numbers == 4  # 표 2개 + 차트 값 2개


def test_cli_prints_table_and_writes_json(tmp_path, capsys):
    prs = _deck()
    s = prs.slides.add_slide(prs.slide_layouts[6])
    _filler(s, 0.25, 0.85)
    prs.save(tmp_path / "a.pptx")
    assert main([str(tmp_path / "a.pptx"), "--json", str(tmp_path / "m.json")]) == 0
    out = capsys.readouterr().out
    assert "| 지표 | a.pptx |" in out and "| 차트 | 0 |" in out
    saved = json.loads((tmp_path / "m.json").read_text(encoding="utf-8"))
    assert saved[0]["slides"] == 1
