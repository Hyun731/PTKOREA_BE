"""구조화 출력이 받지 않는 제약(maxItems 등)은 보내기 전에 빠진다 — 실제 API가 400으로 거절했다
(2026-11-11, 소비자 원문 분류 VOC_SCHEMA의 pain_points maxItems)."""
from app.services.research import VOC_SCHEMA
from integrations.anthropic.client import api_schema


def test_api_schema_drops_unsupported_constraints_but_keeps_property_names():
    schema = {"type": "object", "required": ["maximum", "tags"],
              "properties": {"maximum": {"type": "number", "minimum": 0},  # 속성 이름이 'maximum'이어도 남는다
                             "tags": {"type": "array", "minItems": 3, "maxItems": 3, "items": {"type": "string", "maxLength": 9}},
                             "one": {"type": "array", "minItems": 1, "items": {"type": "string", "enum": ["a", "b"]}}}}
    out = api_schema(schema)
    assert out == {"type": "object", "required": ["maximum", "tags"],
                   "properties": {"maximum": {"type": "number"},
                                  "tags": {"type": "array", "items": {"type": "string"}},
                                  "one": {"type": "array", "minItems": 1, "items": {"type": "string", "enum": ["a", "b"]}}}}
    assert schema["properties"]["tags"]["maxItems"] == 3  # 원본은 그대로


def test_voc_schema_goes_out_without_max_items():
    assert "maxItems" not in str(api_schema(VOC_SCHEMA))


def test_user_content_puts_known_images_before_the_text():
    from integrations.anthropic.client import user_content

    png = b"\x89PNG\r\n\x1a\n" + b"0" * 10
    jpg = b"\xff\xd8\xff" + b"0" * 10
    assert user_content("글") == "글"
    out = user_content("글", [png, b"not-an-image", jpg])
    assert [b["type"] for b in out] == ["image", "image", "text"]
    assert out[0]["source"]["media_type"] == "image/png" and out[1]["source"]["media_type"] == "image/jpeg"
    assert user_content("글", [b"nope"]) == "글"
