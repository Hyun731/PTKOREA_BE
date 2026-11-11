"""P3-5 page insights: evidence-backed cards persist independently from headlines."""
from datetime import date

from app.services.insights import _body_context, check_page_insights, page_insights_from
from core.composition.build import BuildInputs, body_fingerprint, build_deck
from core.composition.chrome import PartFactory
from core.schemas.slidespec import TextBlock
from tests.helpers import load_fixture


def _inputs(**kwargs) -> BuildInputs:
    project, facts, posts = load_fixture()
    return BuildInputs(project=project, facts=facts.facts + posts.facts, posts=posts.posts,
                       generated_on=date(2026, 10, 12), **kwargs)


def _writing(fact_id: str) -> dict:
    def card(title: str, body: str) -> dict:
        return {
            "title": {"parts": [{"type": "text", "text": title}]},
            "body_segments": {"parts": [{"type": "text", "text": body},
                                        {"type": "fact", "fact_id": fact_id, "formatter": "share"}]},
        }

    return {"insights": [card("점유 확인", "본문 수치 "), card("격차 점검", "비교 수치 "),
                         card("운영 우선", "다음 확인 값 ")]}


def test_page_insights_convert_to_three_evidence_backed_cards():
    result = build_deck(_inputs())
    slide = next(slide for slide in result.deck.slides if slide.slide_id == "2-8a")
    facts, _ = _body_context(slide)
    assert facts
    page_writing = _writing(facts[0]["fact_id"])
    model_data = {
        "insights": [
            {"title": [{"text": "점유 확인", "fact_ref": None, "accent": False}],
             "body_segments": [{"text": "본문 수치 ", "fact_ref": None, "accent": False},
                               {"text": "", "fact_ref": 1, "accent": False}]},
            {"title": [{"text": "격차 점검", "fact_ref": None, "accent": False}],
             "body_segments": [{"text": "비교 수치 ", "fact_ref": None, "accent": False},
                               {"text": "", "fact_ref": 1, "accent": False}]},
            {"title": [{"text": "운영 우선", "fact_ref": None, "accent": False}],
             "body_segments": [{"text": "다음 확인 값 ", "fact_ref": None, "accent": False},
                               {"text": "", "fact_ref": 1, "accent": False}]},
        ]
    }
    cards, errors = page_insights_from(model_data, facts, PartFactory(result.metrics.registry))
    assert errors == []
    assert check_page_insights(cards) == []
    assert len(page_writing["insights"]) == 3
    assert all(card["body_segments"].parts[-1].type == "fact" for card in cards)


def test_page_insights_render_from_matching_writing_and_human_empty_override_hides_them():
    baseline = build_deck(_inputs())
    original = next(slide for slide in baseline.deck.slides if slide.slide_id == "2-8a")
    fact_id = _body_context(original)[0][0]["fact_id"]
    stored = _writing(fact_id)
    ai_writing = {"insights": {"2-8a": {"fp": body_fingerprint(original), **stored}}}

    rendered = build_deck(_inputs(ai_writing=ai_writing))
    slide = next(slide for slide in rendered.deck.slides if slide.slide_id == "2-8a")
    bodies = [block for block in slide.blocks if isinstance(block, TextBlock) and block.role == "insight"
              and block.block_id.endswith("_body")]
    assert len(bodies) == 3
    assert all(block.paragraphs[0].parts[-1].type == "fact" for block in bodies)
    assert body_fingerprint(slide) == body_fingerprint(original)

    hidden = build_deck(_inputs(ai_writing=ai_writing, insight_overrides={"2-8a": []}))
    hidden_slide = next(slide for slide in hidden.deck.slides if slide.slide_id == "2-8a")
    assert not [block for block in hidden_slide.blocks if block.block_id.startswith("insight")]
