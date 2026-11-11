"""P3-4 헤드라인 v2 — AI 답을 주장 + 근거로 바꾸고 QC와 같은 규칙으로 검사한다."""
from app.services.insights import check_headline, headline_from
from core.composition.build import build_deck
from core.composition.chrome import PartFactory
from core.schemas.slidespec import Headline, Paragraph, Part
from tests.unit.test_headline_v2 import F, T, _inputs, _share_fact


def test_check_headline_needs_evidence_with_a_number_or_quote():
    claim = [Paragraph(parts=[T("러기지 인지·신뢰는 "), Part(type="text", text="확고한 1위", color="accent")])]
    assert any("근거 줄" in e for e in check_headline(Headline(claim=[Paragraph(parts=[T("러기지 인지 우위")])])))
    assert any("숫자" in e for e in check_headline(Headline(claim=claim, evidence=[Paragraph(parts=[T("고려 "), F()])])))
    ok = Headline(claim=[Paragraph(parts=[T("러기지 인지·신뢰는 확고한 우위")])],
                  evidence=[Paragraph(parts=[T("러기지 고려 "), F(), T("로 경쟁 세트 단독 선두")]),
                            Paragraph(parts=[T("'믿고 사는 브랜드'가 선택 이유")])])
    assert check_headline(ok) == []
    no_ground = Headline(claim=ok.claim, evidence=[Paragraph(parts=[T("경쟁 세트 안에서 앞선 흐름")])])
    assert any("인용" in e for e in check_headline(no_ground))
    many = Headline(claim=ok.claim, evidence=[Paragraph(parts=[T("고려 "), F(), T(" · "), F("F-2"), T(" · "), F("F-3")])])
    assert any("2개" in e for e in check_headline(many))
    raw = Headline(claim=ok.claim, evidence=[Paragraph(parts=[T("고려 61%로 선두")])])
    assert any("근거 없는 숫자" in e for e in check_headline(raw))
    over = Headline(claim=[Paragraph(parts=[T("광고비 투입 확인")])], evidence=ok.evidence)
    assert any("광고비" in e for e in check_headline(over))
    long = Headline(claim=ok.claim, evidence=[Paragraph(parts=[T("가나다라마바사 " * 20), F()])])
    assert any("한 줄" in e for e in check_headline(long))


def test_self_brands_are_never_compared_in_a_headline():
    head = Headline(claim=[Paragraph(parts=[T("샘소나이트 레드가 샘소나이트보다 앞섬")])],
                    evidence=[Paragraph(parts=[T("고려 "), F()])])
    assert any("자사 브랜드끼리" in e for e in check_headline(head, ["샘소나이트", "샘소나이트 레드"]))
    one = Headline(claim=[Paragraph(parts=[T("샘소나이트 레드는 경쟁사 대비 우위")])], evidence=head.evidence)
    assert not any("자사 브랜드끼리" in e for e in check_headline(one, ["샘소나이트", "샘소나이트 레드"]))


def test_model_answer_becomes_claim_with_one_accent_and_evidence_lines():
    r = build_deck(_inputs())
    pf = PartFactory(r.metrics.registry)
    fid = _share_fact(r)
    facts = [{"ref": 1, "fact_id": fid, "formatter": "share"}]
    head, errors = headline_from({"claim": [{"text": "검색 점유 ", "fact_ref": None, "accent": False},
                                            {"text": "우위 축소", "fact_ref": None, "accent": True},
                                            {"text": " 흐름", "fact_ref": None, "accent": True}],
                                  "evidence": [[{"text": "- 자사 점유 ", "fact_ref": None, "accent": False},
                                                {"text": "", "fact_ref": 1, "accent": False}],
                                               [{"text": "없는 수치 ", "fact_ref": None, "accent": False},
                                                {"text": "", "fact_ref": 9, "accent": False}]]}, facts, pf)
    assert errors == ["없는 수치 참조 9"]
    assert [p.color for p in head.claim[0].parts] == [None, "accent", None]  # only one accent keyword
    assert head.evidence[0].parts[0].text == "자사 점유 "  # the server draws the "- " marker
    assert head.evidence[0].parts[1].type == "fact" and head.evidence[0].parts[1].display


def test_names_with_digits_on_the_page_are_names_not_numbers():
    from app.services.insights import _name_parts, digit_names
    from core.composition.chrome import N, P
    from core.schemas.slidespec import Region, SlideSpec, TextBlock

    label = TextBlock(block_id="k", role="caption", region=Region(x=0, y=0, w=10, h=10), size=9, line_spacing=12,
                      paragraphs=[P(N("브랜든 × 29CM 단독 컬렉션"))])
    slide = SlideSpec(slide_id="s", template_id="t", page_role="content", title="x", blocks=[label])
    names = digit_names(slide)
    assert names == ["29CM"]
    parts = _name_parts("29CM 판매 상위권", names)
    assert [(p.type, p.text) for p in parts] == [("name", "29CM"), ("text", " 판매 상위권")]
    head = Headline(claim=[Paragraph(parts=parts)], evidence=[Paragraph(parts=[T("판매 "), F()])])
    assert check_headline(head) == []
