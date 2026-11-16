from pathlib import Path

from pptx import Presentation

from core.quality.qc import Issue, QCReport
from core.rendering.pptx_renderer import render_deck
from core.schemas.slidespec import Crop, DeckSpec, ImageBlock, Region, SlideSpec


def test_quality_findings_are_reviewable_without_blocking_draft_export():
    report = QCReport(issues=[
        Issue("IMAGE_MISSING", "block", "이미지 파일 없음", "이미지 추가", "S1", "hero"),
        Issue("UNBOUND_NUMBER", "block", "근거 연결 없는 숫자", "숫자 확인", "S2", "lead"),
        Issue("NEUTRAL_LEAD", "warn", "중립 리드", "문구 확인", "S2", "lead"),
    ])

    data = report.to_dict()

    assert report.blocks == 2
    assert report.export_blocks == 0
    assert data["review_required"] is True
    assert data["export_blocks"] == 0
    assert [(action["key"], action["slides"]) for action in data["actions"]] == [
        ("images", 1),
        ("numbers", 1),
        ("content", 1),
    ]


def test_missing_image_renders_as_draft_placeholder(tmp_path: Path):
    deck = DeckSpec(
        deck_id="DRAFT",
        project_name="MVP draft",
        slides=[SlideSpec(
            slide_id="S1",
            template_id="draft",
            page_role="content",
            title="초안",
            blocks=[ImageBlock(block_id="hero", region=Region(x=80, y=100, w=500, h=300), asset_id="missing")],
        )],
        plan=[],
    )

    path = render_deck(deck, tmp_path / "draft.pptx")
    slide = Presentation(str(path)).slides[0]
    shapes = {shape.name: shape for shape in slide.shapes}

    assert "hero" in shapes
    assert "hero_placeholder" in shapes
    assert shapes["hero_placeholder"].text == "이미지 추가"


def test_invalid_image_crop_renders_as_draft_placeholder(tmp_path: Path):
    image = tmp_path / "source.png"
    from PIL import Image
    Image.new("RGB", (100, 100), "white").save(image)
    deck = DeckSpec(
        deck_id="DRAFT",
        project_name="MVP draft",
        slides=[SlideSpec(
            slide_id="S1",
            template_id="draft",
            page_role="content",
            title="초안",
            blocks=[ImageBlock(
                block_id="hero",
                region=Region(x=80, y=100, w=500, h=300),
                asset_id="invalid-crop",
                crop=Crop(x=0, y=0, w=0, h=1),
            )],
        )],
        plan=[],
    )

    path = render_deck(deck, tmp_path / "invalid-crop.pptx", lambda _: (str(image), 100, 100))
    slide = Presentation(str(path)).slides[0]

    assert any(shape.name == "hero_placeholder" and shape.text == "이미지 추가" for shape in slide.shapes)
