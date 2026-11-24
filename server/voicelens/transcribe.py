"""Voice note -> text using Telegram's own transcription (not implemented yet)."""


class TranscriptionError(Exception):
    pass


class QuotaExhausted(TranscriptionError):
    pass


class NotAVoiceNote(TranscriptionError):
    pass


class TranscriptionFailed(TranscriptionError):
    pass


async def transcribe_voice_note(client, peer, msg_id, *, sleep=None, max_attempts=10):
    raise NotImplementedError
