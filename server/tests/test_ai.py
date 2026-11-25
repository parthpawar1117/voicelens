"""AI writer: short reply drafts and channel digests via Groq (faked with httpx.MockTransport)."""

import json

import httpx

from voicelens.ai import AIWriter, DEFAULT_MODEL, GROQ_URL


def writer(payload=None, status=200, finish="stop"):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        assert str(request.url) == GROQ_URL
        assert request.headers["authorization"] == "Bearer test-key"
        body = {"choices": [{"finish_reason": finish, "message": {"content": json.dumps(payload)}}]}
        return httpx.Response(status, json=body)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return AIWriter(api_key="test-key", client=client), calls


async def test_two_short_drafts_cleaned_for_the_g2_font():
    w, _ = writer({"replies": ["Yes, joining at 5 \U0001F44D", "Running 10 min late", "extra"]})
    assert await w.draft_replies("Rahul", ["Rahul: meeting moved to 5"], "Are you joining?") == \
        ["Yes, joining at 5", "Running 10 min late"]


async def test_request_is_json_mode_with_the_message_as_data():
    w, calls = writer({"replies": ["Ok", "Later"]})
    await w.draft_replies("Rahul", [], "Hi?")
    req = calls[0]
    assert req["model"] == DEFAULT_MODEL
    assert req["response_format"] == {"type": "json_object"}
    assert req["messages"][0]["role"] == "system"
    assert "<message>" in req["messages"][1]["content"]  # chat text is data, not instructions


async def test_drafts_never_block_the_glasses_on_errors():
    w, _ = writer(status=500)
    assert await w.draft_replies("A", [], "hi") == []
    w2, _ = writer({"replies": ["x"]}, finish="length")
    assert await w2.draft_replies("A", [], "hi") == []

    def boom(request):
        raise httpx.ConnectError("offline")
    w3 = AIWriter(api_key="k", client=httpx.AsyncClient(transport=httpx.MockTransport(boom)))
    assert await w3.draft_replies("A", [], "hi") == []


async def test_bad_json_from_the_model_gives_nothing():
    w, _ = writer("not an object")
    assert await w.draft_replies("A", [], "hi") == []


async def test_digest_returns_at_most_five_short_lines():
    w, calls = writer({"lines": [f"Line {i}" for i in range(8)]})
    lines = await w.digest({"Crypto Alpha": ["BTC broke 100k", "ETH upgrade Friday"], "Work": ["Deploy at 6"]})
    assert lines == [f"Line {i}" for i in range(5)]
    prompt = calls[0]["messages"][1]["content"]
    assert "Crypto Alpha" in prompt and "Deploy at 6" in prompt


async def test_empty_digest_makes_no_api_call():
    w, calls = writer({"lines": []})
    assert await w.digest({}) == []
    assert calls == []


def test_writer_is_off_without_a_key(monkeypatch):
    from voicelens.ai import make_writer
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    assert make_writer() is None


def test_model_can_be_changed_in_env(monkeypatch):
    from voicelens.ai import make_writer
    monkeypatch.setenv("GROQ_API_KEY", "k")
    monkeypatch.setenv("GROQ_MODEL", "llama-3.1-8b-instant")
    assert make_writer().model == "llama-3.1-8b-instant"


def test_default_is_a_model_groq_still_serves():
    # llama-3.3-70b-versatile was retired (404 model_not_found on Nov 26, 2026).
    assert DEFAULT_MODEL == "openai/gpt-oss-120b"


async def test_reasoning_models_get_low_effort_others_do_not():
    w, calls = writer({"replies": ["Ok", "Later"]})
    await w.draft_replies("Rahul", [], "Hi?")
    assert calls[0]["reasoning_effort"] == "low"  # fastest on gpt-oss: 548 ms measured
    w.model = "llama-3.1-8b-instant"
    await w.draft_replies("Rahul", [], "Hi?")
    assert "reasoning_effort" not in calls[1]


async def test_retries_once_when_groq_rejects_unfinished_json():
    # Seen live: the digest failed 2 of 3 times with 400 json_validate_failed.
    calls = []

    def handler(request):
        calls.append(json.loads(request.content))
        if len(calls) == 1:
            return httpx.Response(400, json={"error": {"code": "json_validate_failed", "message": "Failed to validate JSON"}})
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": json.dumps({"lines": ["BTC 100k"]})}}]})

    w = AIWriter(api_key="test-key", client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    assert await w.digest({"Crypto": ["BTC broke 100k"]}) == ["BTC 100k"]
    assert len(calls) == 2


async def test_digest_gets_more_room_than_a_draft():
    w, calls = writer({"lines": ["x"]})
    await w.digest({"Crypto": ["BTC broke 100k"]})
    await w.draft_replies("A", [], "hi")
    assert calls[0]["max_tokens"] >= 1000 and calls[1]["max_tokens"] <= 400
