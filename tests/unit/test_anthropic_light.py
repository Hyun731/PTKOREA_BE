"""선별·분류용 저가 모델 호출: 모델은 ANTHROPIC_MODEL_LIGHT(기본 Haiku), 서버 거절 대체(fallbacks)는 보내지 않는다."""
from types import SimpleNamespace

from integrations.anthropic import client as ac


class FakeClient:
    def __init__(self):
        self.kw = None
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **kw):
        self.kw = kw
        return SimpleNamespace(usage=SimpleNamespace(input_tokens=10, output_tokens=5), model=kw["model"],
                               stop_reason="end_turn", content=[SimpleNamespace(type="text", text='{"relevant": true}')])


def test_light_call_uses_light_model_without_fallbacks(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-opus-5-5")
    monkeypatch.delenv("ANTHROPIC_MODEL_LIGHT", raising=False)
    fake = FakeClient()
    res = ac.structured("s", "u", {"type": "object", "properties": {}}, client=fake, light=True, effort="low")
    assert fake.kw["model"] == "claude-haiku-5-5" and "fallbacks" not in fake.kw and "betas" not in fake.kw
    assert res.data == {"relevant": True} and res.cost_usd < 0.00001


def test_default_call_keeps_main_model_and_fallbacks(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-opus-5-5")
    fake = FakeClient()
    ac.structured("s", "u", {"type": "object", "properties": {}}, client=fake)
    assert fake.kw["model"] == "claude-opus-5-5" and fake.kw["fallbacks"] == "default"
