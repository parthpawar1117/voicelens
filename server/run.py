"""Run the VoiceLens server: Telegram listener + transcription + inbox API.

    server/.venv/Scripts/python server/run.py

- Watches the chats in server/watched_chats.json (default: your Saved Messages).
- Texts go into the inbox at once; voice notes are transcribed first
  (Telegram for Premium, else local Whisper on the GPU, kept warm).
- Serves the inbox on http://127.0.0.1:8787 for the G2 app.

Read-only on Telegram for now: it never sends, deletes or marks anything.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import uvicorn  # noqa: E402
from telethon import TelegramClient, events  # noqa: E402

from voicelens import local_whisper  # noqa: E402
from voicelens.app import create_app  # noqa: E402
from voicelens.config import SERVER_DIR, load_settings  # noqa: E402
from voicelens.hybrid import transcribe_hybrid  # noqa: E402
from voicelens.inbox import Inbox  # noqa: E402
from voicelens.ingest import backfill, is_watched, load_watched, to_inbox_item  # noqa: E402
from voicelens.local_whisper import LocalWhisper  # noqa: E402
from voicelens.transcribe import transcribe_voice_note  # noqa: E402

TMP = SERVER_DIR / "tmp"
BACKFILL_PER_CHAT = 10


def chat_title(chat, me_id: int) -> str:
    if getattr(chat, "id", None) == me_id:
        return "Saved Messages"
    return getattr(chat, "title", None) or " ".join(
        p for p in (getattr(chat, "first_name", None), getattr(chat, "last_name", None)) if p
    ) or "Unknown"


async def main() -> None:
    settings = load_settings()
    TMP.mkdir(exist_ok=True)
    inbox = Inbox()
    local = LocalWhisper()
    hybrid_state: dict = {}

    print("Warming up Whisper...")
    await local.warm_up()
    print(f"Whisper ready on {local_whisper.loaded_device}.")
    stop = asyncio.Event()
    if local_whisper.loaded_device == "cuda":
        asyncio.create_task(local.keep_alive(2.0, stop=stop))

    async with TelegramClient(str(settings.session_path), settings.api_id, settings.api_hash) as client:
        me = await client.get_me()
        watched = load_watched(SERVER_DIR / "watched_chats.json", my_id=me.id)
        print(f"Watching {len(watched)} chat(s).")

        async def transcribe(message):
            path = TMP / f"in_{message.chat_id}_{message.id}.ogg"

            async def telegram(peer, msg_id):
                return await transcribe_voice_note(client, peer=peer, msg_id=msg_id)

            async def download(peer, msg_id):
                return await message.download_media(file=str(path))

            try:
                return await transcribe_hybrid(
                    peer=message.chat_id, msg_id=message.id, telegram=telegram,
                    local=local, download=download, state=hybrid_state,
                )
            finally:
                path.unlink(missing_ok=True)

        # Load recent history so the inbox isn't empty after a restart.
        for chat_id in watched:
            chat = await client.get_entity(chat_id)
            history = [m async for m in client.iter_messages(chat_id, limit=BACKFILL_PER_CHAT)]
            added = await backfill(history, inbox, chat_name=chat_title(chat, me.id), transcribe=transcribe)
            print(f"Loaded {added} recent message(s) from {chat_title(chat, me.id)}.")

        @client.on(events.NewMessage())
        async def on_message(event):
            message = event.message
            if not is_watched(message.chat_id, watched):
                return
            chat = await event.get_chat()
            try:
                item = await to_inbox_item(message, chat_name=chat_title(chat, me.id), transcribe=transcribe)
            except Exception as err:  # keep serving on any single failure
                print(f"Could not process message {message.id}: {type(err).__name__}: {err}")
                return
            if item:
                inbox.add(item)
                print(f"+ {item.kind:5} from {item.chat_name}: {item.text[:60]}")

        server = uvicorn.Server(uvicorn.Config(
            create_app(inbox), host="127.0.0.1", port=settings.port, log_level="warning",
        ))
        print(f"Inbox API on http://127.0.0.1:{settings.port}/inbox")
        try:
            await asyncio.gather(server.serve(), client.run_until_disconnected())
        finally:
            stop.set()


if __name__ == "__main__":
    asyncio.run(main())
