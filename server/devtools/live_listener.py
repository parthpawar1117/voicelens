"""Live transcription listener for speed testing.

Run from the repo root:
    server/.venv/Scripts/python server/devtools/live_listener.py

Then send voice notes (or forward audio) to your own Saved Messages. Each one is
downloaded and transcribed right away with the hybrid engine, and the result
with a timing breakdown is written to server/tmp/live_feed.json, which the
dashboard (http://127.0.0.1:8800) shows live.

Read-only on Telegram: it never sends, deletes or marks anything as read/listened.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from telethon import TelegramClient, events  # noqa: E402

from voicelens.config import SERVER_DIR, load_settings  # noqa: E402
from voicelens.hybrid import transcribe_hybrid  # noqa: E402
from voicelens.live_feed import add_entry, summarize  # noqa: E402
from voicelens import local_whisper  # noqa: E402
from voicelens.local_whisper import LocalWhisper  # noqa: E402
from voicelens.transcribe import TranscriptionError, transcribe_voice_note  # noqa: E402

TMP = SERVER_DIR / "tmp"
FEED_FILE = TMP / "live_feed.json"

feed: list[dict] = []
status = {"listening": False, "model_ready": False, "processing": None}


def save() -> None:
    TMP.mkdir(exist_ok=True)
    payload = {**status, "updated": datetime.now().strftime("%H:%M:%S"),
               "summary": summarize(feed), "feed": feed}
    tmp = FEED_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(FEED_FILE)  # atomic swap so the dashboard never reads half a file


async def main() -> None:
    global feed
    settings = load_settings()
    local = LocalWhisper()
    hybrid_state: dict = {}
    save()

    print("Loading Whisper model and warming it up (kept warm for fair timings)...")
    await local.warm_up()
    status["model_ready"] = True
    status["device"] = local_whisper.loaded_device  # "cuda" (GPU) or "cpu"
    print(f"Model ready on {status['device']}.")
    save()

    async with TelegramClient(str(settings.session_path), settings.api_id, settings.api_hash) as client:

        async def telegram(peer, msg_id):
            return await transcribe_voice_note(client, peer=peer, msg_id=msg_id)

        @client.on(events.NewMessage(chats="me"))
        async def on_message(event):
            global feed
            message = event.message
            if not (message.voice or message.audio):
                return
            received = time.perf_counter()
            duration = float(message.file.duration or 0)
            status["processing"] = f"{duration:.0f} s note"
            save()
            print(f"New {'voice note' if message.voice else 'audio'} ({duration:.0f} s)...")

            path = TMP / f"live_{message.id}.ogg"
            timings: dict = {}

            async def download(peer, msg_id):
                t = time.perf_counter()
                result = await message.download_media(file=str(path))
                timings["download_s"] = round(time.perf_counter() - t, 2)
                return result

            entry = {"id": message.id, "duration": duration,
                     "kind": "voice" if message.voice else "audio",
                     "received": datetime.now().strftime("%H:%M:%S")}
            try:
                t = time.perf_counter()
                result = await transcribe_hybrid(
                    peer="me", msg_id=message.id, telegram=telegram, local=local,
                    download=download, state=hybrid_state,
                )
                total_engine = time.perf_counter() - t
                done_utc = datetime.now(timezone.utc)
                entry.update(
                    source=result.source,
                    text=result.text,
                    download_s=timings.get("download_s", 0.0),
                    transcribe_s=round(total_engine - timings.get("download_s", 0.0), 2),
                    pipeline_s=round(time.perf_counter() - received, 2),
                    # From the moment Telegram stamped the message (1 s resolution).
                    total_s=round((done_utc - message.date).total_seconds(), 1),
                    steps=dict(local.last_timings) if result.source == "local" else {},
                )
                print(f"  -> {result.source} in {entry['transcribe_s']} s {entry['steps']}: {result.text}")
            except (TranscriptionError, Exception) as err:  # keep listening on any failure
                entry["error"] = f"{type(err).__name__}: {err}"
                print(f"  -> failed: {entry['error']}")
            finally:
                path.unlink(missing_ok=True)

            feed = add_entry(feed, entry)
            status["processing"] = None
            save()

        # Keep the GPU from clocking down between notes (1.2 s -> 0.3 s after idle).
        stop_keep_alive = asyncio.Event()
        keep_alive_task = None
        if status.get("device") == "cuda":
            keep_alive_task = asyncio.create_task(local.keep_alive(2.0, stop=stop_keep_alive))
        status["keep_alive"] = keep_alive_task is not None

        status["listening"] = True
        save()
        print("Listening. Send voice notes to your Saved Messages. Ctrl+C to stop.")
        try:
            await client.run_until_disconnected()
        finally:
            stop_keep_alive.set()
            status["listening"] = False
            save()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        status["listening"] = False
        save()
