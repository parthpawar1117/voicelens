"""Day-1 check: turn your latest voice notes into text with the hybrid engine.

1. Send one or more voice notes to your own "Saved Messages" in Telegram.
2. Run:  server/.venv/Scripts/python server/try_transcribe.py

For each of the newest 3 voice notes it tries Telegram's own transcription
(Premium) and falls back to local Whisper on this computer. The first local run
downloads the Whisper model (~145 MB). The script only reads; it never sends,
deletes or marks anything. Downloaded audio is removed afterwards.
"""

import asyncio
import json
import time
from datetime import datetime
from pathlib import Path

from telethon import TelegramClient

from voicelens.config import SERVER_DIR, load_settings
from voicelens.hybrid import transcribe_hybrid
from voicelens.local_whisper import LocalWhisper
from voicelens.transcribe import TranscriptionError, transcribe_voice_note

TMP = SERVER_DIR / "tmp"


async def main() -> None:
    settings = load_settings()
    TMP.mkdir(exist_ok=True)
    local = LocalWhisper()
    state: dict = {}

    async with TelegramClient(str(settings.session_path), settings.api_id, settings.api_hash) as client:
        voice_notes = [m async for m in client.iter_messages("me", limit=50) if m.voice][:3]
        if not voice_notes:
            print("No voice note in your last 50 Saved Messages. Send one and retry.")
            return

        async def telegram(peer, msg_id):
            return await transcribe_voice_note(client, peer=peer, msg_id=msg_id)

        async def download(peer, msg_id):
            message = next(m for m in voice_notes if m.id == msg_id)
            return await message.download_media(file=str(TMP / f"{msg_id}.ogg"))

        notes = []
        for message in voice_notes:
            print(f"\nVoice note {message.date:%Y-%m-%d %H:%M} UTC, {message.file.duration or '?'} s")
            started = time.perf_counter()
            entry = {"duration": message.file.duration}
            try:
                result = await transcribe_hybrid(
                    peer="me", msg_id=message.id, telegram=telegram,
                    local=local, download=download, state=state,
                )
            except TranscriptionError as err:
                print(f"  failed: {type(err).__name__}: {err}")
                notes.append({**entry, "error": f"{type(err).__name__}: {err}"})
                continue
            finally:
                Path(TMP / f"{message.id}.ogg").unlink(missing_ok=True)
            seconds = round(time.perf_counter() - started, 1)
            print(f"  source: {result.source}  ({seconds} s)")
            print(f"  text:   {result.text}")
            notes.append({**entry, "source": result.source, "seconds": seconds, "text": result.text})

        # Read by the live dashboard (server/devtools/dashboard.py). Gitignored.
        (TMP / "last_run.json").write_text(
            json.dumps({"ran_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "notes": notes},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


if __name__ == "__main__":
    asyncio.run(main())
