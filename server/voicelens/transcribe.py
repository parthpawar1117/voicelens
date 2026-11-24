"""Voice note -> text using Telegram's own transcription.

We call messages.transcribeAudio rather than a third-party speech model, so
message content never leaves Telegram (API Terms 1.5). Non-Premium users get a
weekly free quota; Telegram reports what is left in trial_remains_num.

Telegram may answer with pending=True and fill in the text later. We poll by
repeating the request (it returns the current state) instead of listening for
updateTranscribedAudio, which keeps this function self-contained.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Awaitable, Callable

from telethon.errors import RPCError
from telethon.tl.functions.messages import TranscribeAudioRequest


class TranscriptionError(Exception):
    pass


class QuotaExhausted(TranscriptionError):
    """Free weekly transcriptions used up (PREMIUM_ACCOUNT_REQUIRED)."""


class NotAVoiceNote(TranscriptionError):
    pass


class TranscriptionFailed(TranscriptionError):
    pass


@dataclass(frozen=True)
class Transcript:
    text: str
    complete: bool
    trial_remaining: int | None


_ERRORS: dict[str, type[TranscriptionError]] = {
    "PREMIUM_ACCOUNT_REQUIRED": QuotaExhausted,
    "MSG_VOICE_MISSING": NotAVoiceNote,
}


async def transcribe_voice_note(
    client,
    peer,
    msg_id: int,
    *,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    max_attempts: int = 10,
    poll_seconds: float = 1.0,
) -> Transcript:
    result = None
    for attempt in range(max_attempts):
        try:
            result = await client(TranscribeAudioRequest(peer=peer, msg_id=msg_id))
        except RPCError as err:
            error_type = _ERRORS.get(err.message, TranscriptionFailed)
            raise error_type(err.message) from err
        if not result.pending:
            break
        if attempt < max_attempts - 1:
            await sleep(poll_seconds)

    return Transcript(
        text=result.text,
        complete=not result.pending,
        trial_remaining=result.trial_remains_num,
    )
