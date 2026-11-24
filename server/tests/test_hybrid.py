"""Hybrid transcription: Telegram first, local Whisper when Premium is missing."""

import pytest

from voicelens.hybrid import transcribe_hybrid
from voicelens.transcribe import NotAVoiceNote, QuotaExhausted, Transcript


class FakeTelegram:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result, error, 0

    async def __call__(self, peer, msg_id):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result


class FakeLocal:
    def __init__(self, text="local text"):
        self.text, self.calls = text, []

    async def __call__(self, audio_path):
        self.calls.append(audio_path)
        return self.text


async def fake_download(peer, msg_id):
    return f"/tmp/{msg_id}.ogg"


async def test_uses_telegram_when_it_works_and_never_touches_local():
    telegram = FakeTelegram(result=Transcript("from telegram", True, None))
    local = FakeLocal()
    result = await transcribe_hybrid(
        peer="me", msg_id=5, telegram=telegram, local=local, download=fake_download,
    )
    assert result.text == "from telegram"
    assert result.source == "telegram"
    assert local.calls == []


async def test_falls_back_to_local_whisper_when_premium_is_missing():
    telegram = FakeTelegram(error=QuotaExhausted("FORBIDDEN"))
    local = FakeLocal("meeting moved to 5 pm")
    result = await transcribe_hybrid(
        peer="me", msg_id=5, telegram=telegram, local=local, download=fake_download,
    )
    assert result.text == "meeting moved to 5 pm"
    assert result.source == "local"
    assert local.calls == ["/tmp/5.ogg"]


async def test_remembers_premium_is_missing_and_skips_telegram_next_time():
    telegram = FakeTelegram(error=QuotaExhausted("FORBIDDEN"))
    local = FakeLocal()
    state = {}
    for msg_id in (1, 2, 3):
        await transcribe_hybrid(
            peer="me", msg_id=msg_id, telegram=telegram, local=local,
            download=fake_download, state=state,
        )
    assert telegram.calls == 1
    assert len(local.calls) == 3


async def test_other_errors_are_not_hidden_by_the_fallback():
    telegram = FakeTelegram(error=NotAVoiceNote("MSG_VOICE_MISSING"))
    with pytest.raises(NotAVoiceNote):
        await transcribe_hybrid(
            peer="me", msg_id=5, telegram=telegram, local=FakeLocal(), download=fake_download,
        )


async def test_without_a_local_engine_the_quota_error_is_raised():
    telegram = FakeTelegram(error=QuotaExhausted("FORBIDDEN"))
    with pytest.raises(QuotaExhausted):
        await transcribe_hybrid(
            peer="me", msg_id=5, telegram=telegram, local=None, download=fake_download,
        )
