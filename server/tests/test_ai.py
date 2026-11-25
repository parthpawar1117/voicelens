"""AI writer: short reply drafts and channel digests via the Claude API (faked here)."""

import json
from types import SimpleNamespace

from voicelens.ai import AIWriter


class FakeMessages:
    def __init__(self, payload=None, error=None, stop_reason="end_turn"):
        self.payload, self.error, self.stop_reason, self.calls = payload, error, stop_reason, []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(stop_reason=self.stop_reason,
                               content=[SimpleNamespace(type="text", text=json.dumps(self.payload))])


def writer(**kw):
    msgs = FakeMessages(**kw)
    return AIWriter(SimpleNamespace(beta=SimpleNamespace(messages=msgs))), msgs


async def test_two_short_drafts_cleaned_for_the_g2_font():
    w, msgs = writer(payload={"replies": ["Yes, joining at 5 \U0001F44D", "Running 10 min late", "extra"]})
    drafts = await w.draft_replies("Rahul", ["Rahul: meeting moved to 5"], "Are you joining?")
    assert drafts == ["Yes, joining at 5", "Running 10 min late"]


async def test_request_is_fast_structured_and_has_a_refusal_fallback():
    w, msgs = writer(payload={"replies": ["Ok", "Later"]})
    await w.draft_replies("Rahul", [], "Hi?")
    call = msgs.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["output_config"]["effort"] == "low"
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert call["fallbacks"] == "default" and "server-side-fallback-2026-07-01" in call["betas"]
    # The incoming message is data, not instructions.
    assert "<message>" in call["messages"][0]["content"]


async def test_drafts_never_block_the_glasses_on_errors_or_refusals():
    w, _ = writer(error=RuntimeError("network down"))
    assert await w.draft_replies("A", [], "hi") == []
    w2, _ = writer(payload={"replies": ["x"]}, stop_reason="refusal")
    assert await w2.draft_replies("A", [], "hi") == []


async def test_digest_returns_at_most_five_short_lines():
    w, msgs = writer(payload={"lines": [f"Line {i}" for i in range(8)]})
    lines = await w.digest({"Crypto Alpha": ["BTC broke 100k", "ETH upgrade Friday"], "Work": ["Deploy at 6"]})
    assert lines == [f"Line {i}" for i in range(5)]
    prompt = msgs.calls[0]["messages"][0]["content"]
    assert "Crypto Alpha" in prompt and "Deploy at 6" in prompt


async def test_empty_digest_makes_no_api_call():
    w, msgs = writer(payload={"lines": []})
    assert await w.digest({}) == []
    assert msgs.calls == []


def test_writer_is_off_without_a_key(monkeypatch):
    from voicelens.ai import make_writer
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert make_writer() is None
