"""Day-1 check: can Telegram transcribe your voice notes through the API?

1. Send a voice note to your own "Saved Messages" in Telegram.
2. Run:  server/.venv/Scripts/python server/try_transcribe.py

It finds the latest voice note in Saved Messages, asks Telegram to transcribe it
and prints the text plus your remaining free transcriptions (non-Premium).
It only reads; it never sends, deletes or marks anything.
"""

import asyncio

from telethon import TelegramClient

from voicelens.config import load_settings
from voicelens.transcribe import TranscriptionError, transcribe_voice_note


async def main() -> None:
    settings = load_settings()
    async with TelegramClient(str(settings.session_path), settings.api_id, settings.api_hash) as client:
        async for message in client.iter_messages("me", limit=50):
            if message.voice:
                break
        else:
            print("No voice note in your last 50 Saved Messages. Send one and retry.")
            return

        print(f"Voice note from {message.date:%Y-%m-%d %H:%M}, {message.file.duration or '?'} s")
        try:
            result = await transcribe_voice_note(client, peer="me", msg_id=message.id)
        except TranscriptionError as err:
            print(f"Transcription failed: {type(err).__name__}: {err}")
            return

        print(f"Text: {result.text}")
        print(f"Complete: {result.complete}")
        if result.trial_remaining is not None:
            print(f"Free transcriptions left this week: {result.trial_remaining}")
        else:
            print("No trial counter returned (Premium account, or unlimited).")


if __name__ == "__main__":
    asyncio.run(main())
