"""Hybrid transcription: Telegram's own engine first, local Whisper as fallback.

Premium users get Telegram's transcription, so audio never leaves Telegram.
Without Premium (free quota can be 0/week), the voice note is downloaded and
transcribed by a Whisper model running on the user's own machine. The result
records which engine produced it so the glasses can label it honestly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable, Literal

from voicelens.transcribe import QuotaExhausted, Transcript

TelegramEngine = Callable[[object, int], Awaitable[Transcript]]
LocalEngine = Callable[[str], Awaitable[str]]
Downloader = Callable[[object, int], Awaitable[str]]


@dataclass(frozen=True)
class HybridTranscript:
    text: str
    source: Literal["telegram", "local"]
    complete: bool = True
    trial_remaining: int | None = None


async def transcribe_hybrid(
    *,
    peer,
    msg_id: int,
    telegram: TelegramEngine,
    local: LocalEngine | None,
    download: Downloader,
    state: dict | None = None,
) -> HybridTranscript:
    state = state if state is not None else {}

    if not state.get("premium_missing"):
        try:
            result = await telegram(peer, msg_id)
            return HybridTranscript(
                text=result.text,
                source="telegram",
                complete=result.complete,
                trial_remaining=result.trial_remaining,
            )
        except QuotaExhausted:
            if local is None:
                raise
            # Don't ask Telegram again for every message this session.
            state["premium_missing"] = True

    if local is None:
        raise QuotaExhausted("Telegram transcription unavailable and no local engine")

    audio_path = await download(peer, msg_id)
    text = await local(audio_path)
    return HybridTranscript(text=text, source="local")
