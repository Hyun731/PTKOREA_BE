"""2-4 브랜드별 상위 게시물 (core/composition/owned.py)."""
from datetime import date

from PIL import Image

from core.composition.build import BuildInputs, build_deck
from core.quality.qc import run_qc
from core.schemas.materials import AssetRef, OwnedPostRef
from core.schemas.slidespec import ImageBlock, TableBlock
from tests.helpers import load_fixture


def _asset(id_, status="accepted", tmp_path=None):
    path = str(tmp_path / f"{id_}.jpg")
    Image.new("RGB", (800, 450), (10, 20, 30)).save(path, "JPEG")
    return AssetRef(id=id_, source_id=None, path=path, width=800, height=450, review_status=status)


def _post(id_, likes, tmp_path, asset_status="accepted", brand_id="B1"):
    return OwnedPostRef(id=id_, brand_id=brand_id, channel="instagram", url=f"https://instagram.com/p/{id_}/",
                        posted_at=date(2026, 9, 1), likes=likes, comments=likes // 10,
                        asset=_asset(f"AS-{id_}", asset_status, tmp_path))


def test_top_posts_ranks_by_likes_and_requires_accepted_asset(tmp_path):
    project, _, _ = load_fixture()
    posts = [_post("p1", 500, tmp_path), _post("p2", 900, tmp_path), _post("p3", 100, tmp_path, asset_status="candidate")]
    cfg = project.model_copy(update={"enabled_slides": ["2-4"]})
    result = build_deck(BuildInputs(project=cfg, facts=[], owned_posts=posts, generated_on=date(2026, 10, 12)))
    slide = next(s for s in result.deck.slides if s.slide_id == "2-4")
    img = next(b for b in slide.blocks if isinstance(b, ImageBlock))
    assert img.asset_id == "AS-p2"  # highest likes among accepted-asset posts
    table = next(b for b in slide.blocks if isinstance(b, TableBlock))
    assert len(table.rows) == 2  # p3 excluded: its asset isn't accepted
    assert img.asset_id in result.assets  # BuildResult.assets must resolve owned-post assets too

    qc = run_qc(result.deck, result.metrics.registry, lambda aid: result.assets.get(aid))
    blocking = [i for i in qc.issues if i.severity == "block" and i.slide_id == "2-4"]
    assert blocking == [], blocking


def test_top_posts_absent_without_accepted_images(tmp_path):
    project, _, _ = load_fixture()
    posts = [_post("p1", 500, tmp_path, asset_status="candidate")]
    cfg = project.model_copy(update={"enabled_slides": ["2-4"]})
    result = build_deck(BuildInputs(project=cfg, facts=[], owned_posts=posts, generated_on=date(2026, 10, 12)))
    assert not any(s.slide_id == "2-4" for s in result.deck.slides)
    slot = next(p for p in result.deck.plan if p.slot_id == "2-4")
    assert slot.readiness == "needs_input"
