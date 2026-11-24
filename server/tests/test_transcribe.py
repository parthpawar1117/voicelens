"""Transcription goes through Telegram's own messages.transcribeAudio.

A fake client stands in for Telethon: it is awaited with a request and returns
queued responses, which is how TelegramClient.__call__ behaves.
"""

import pytest
from telethon.errors import RPCError
from telethon.tl.types.messages import TranscribedAudio

from voicelens.transcribe import (
    NotAVoiceNote,
    QuotaExhausted,
    TranscriptionFailed,
    transcribe_voice_note,
)


class FakeClient:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    async def __call__(self, request):
        self.requests.append(request)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def done(text, trial=None):
    return TranscribedAudio(
        transcription_id=1, text=text, pending=False,
        trial_remains_num=trial, trial_remains_until_date=None,
    )


def pending(text=""):
    return TranscribedAudio(
        transcription_id=1, text=text, pending=True,
        trial_remains_num=None, trial_remains_until_date=None,
    )


async def no_sleep(_seconds):
    return None


def rpc(message):
    return RPCError(request=None, message=message, code=400)


async def test_returns_text_when_telegram_answers_immediately():
    client = FakeClient(done("Meeting moved to 5 pm"))
    result = await transcribe_voice_note(client, peer="me", msg_id=42, sleep=no_sleep)
    assert result.text == "Meeting moved to 5 pm"
    assert client.requests[0].msg_id == 42


async def test_polls_until_transcription_is_no_longer_pending():
    client = FakeClient(pending(), pending("Meeting"), done("Meeting moved to 5 pm"))
    result = await transcribe_voice_note(client, peer="me", msg_id=42, sleep=no_sleep)
    assert result.text == "Meeting moved to 5 pm"
    assert len(client.requests) == 3


async def test_reports_remaining_free_transcriptions_for_non_premium_users():
    client = FakeClient(done("hi", trial=7))
    result = await transcribe_voice_note(client, peer="me", msg_id=1, sleep=no_sleep)
    assert result.trial_remaining == 7


async def test_gives_up_after_max_attempts_and_returns_partial_text():
    client = FakeClient(pending("Meet"), pending("Meeting"), pending("Meeting moved"))
    result = await transcribe_voice_note(
        client, peer="me", msg_id=1, sleep=no_sleep, max_attempts=3,
    )
    assert result.text == "Meeting moved"
    assert result.complete is False


async def test_premium_required_error_means_free_quota_is_used_up():
    client = FakeClient(rpc("PREMIUM_ACCOUNT_REQUIRED"))
    with pytest.raises(QuotaExhausted):
        await transcribe_voice_note(client, peer="me", msg_id=1, sleep=no_sleep)


async def test_non_voice_message_is_rejected_clearly():
    client = FakeClient(rpc("MSG_VOICE_MISSING"))
    with pytest.raises(NotAVoiceNote):
        await transcribe_voice_note(client, peer="me", msg_id=1, sleep=no_sleep)


async def test_other_telegram_errors_become_transcription_failed():
    client = FakeClient(rpc("TRANSCRIPTION_FAILED"))
    with pytest.raises(TranscriptionFailed):
        await transcribe_voice_note(client, peer="me", msg_id=1, sleep=no_sleep)
