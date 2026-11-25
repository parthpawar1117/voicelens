"""Run the VoiceLens server: Telegram listener + transcription + inbox API.

    server/.venv/Scripts/python server/run.py

- Watches the chats you pick on the dashboard (default: your Saved Messages).
- AI reply drafts and channel digests with ANTHROPIC_API_KEY in server/.env.
- Texts go into the inbox at once; voice notes are transcribed first
  (Telegram for Premium, else local Whisper on the GPU, kept warm).
- Serves the inbox on http://127.0.0.1:8787 for the G2 app.

Sends a reply only after the glasses confirm (3 s countdown), only to picked
chats. It never deletes anything or marks voice notes as listened.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import uvicorn  # noqa: E402
from telethon import TelegramClient, events  # noqa: E402

from voicelens import local_whisper  # noqa: E402
from voicelens.ai import make_writer  # noqa: E402
from voicelens.app import create_app  # noqa: E402
from voicelens.chats import ChatDirectory  # noqa: E402
from voicelens.config import SERVER_DIR, load_settings  # noqa: E402
from voicelens.hybrid import transcribe_hybrid  # noqa: E402
from voicelens.inbox import Inbox  # noqa: E402
from voicelens.ingest import backfill, is_watched, should_show, to_inbox_item  # noqa: E402
from voicelens.local_whisper import LocalWhisper  # noqa: E402
from voicelens.quick_replies import QuickReplyStore  # noqa: E402
from voicelens.reply import ReplyService  # noqa: E402
from devtools.demo_friend import bot_id_from_token  # noqa: E402
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
        extra = set()
        if settings.demo_bot_token:  # demo videos: the bot plays "the friend"
            extra.add(bot_id_from_token(settings.demo_bot_token))
            print("Demo friend bot chat is watched.")
        chats = ChatDirectory(SERVER_DIR / "watched_chats.json", my_id=me.id)
        watched = chats.watched  # one live set: picks on the dashboard apply at once
        watched.update(extra)
        print(f"Watching {len(watched)} chat(s).")
        writer = make_writer()
        print("AI drafts and digests: " + ("on (Claude API)" if writer else "off (add ANTHROPIC_API_KEY to server/.env)"))

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

        # Telethon can only open chats it has seen. Loading the chat list first
        # lets it find e.g. the demo bot (crashed with "Could not find the input
        # entity" before).
        dialogs = await client.get_dialogs()
        chats.set_known([(d.id, chat_title(d.entity, me.id),
                          "channel" if d.is_channel and not d.is_group else "group" if d.is_group else "user")
                         for d in dialogs])
        print(f"Found {len(dialogs)} chats you can pick on the dashboard.")

        async def add_drafts(item):
            """Prepare AI reply drafts as soon as a message arrives (ready before you open it)."""
            if writer is None:
                return
            recent = [f"{x.chat_name}: {x.text}" for x in reversed(inbox.items()) if x.chat_id == item.chat_id][-6:]
            drafts = await writer.draft_replies(item.chat_name, recent, item.text)
            if drafts:
                inbox.attach_drafts(item.chat_id, item.id, drafts)

        # Load recent history so the inbox isn't empty after a restart.
        for chat_id in watched:
            try:
                chat = await client.get_entity(chat_id)
                history = [m async for m in client.iter_messages(chat_id, limit=BACKFILL_PER_CHAT)
                           if should_show(m, me.id)]
                added = await backfill(history, inbox, chat_name=chat_title(chat, me.id), transcribe=transcribe)
                print(f"Loaded {added} recent message(s) from {chat_title(chat, me.id)}.")
            except Exception as err:  # one unknown chat must not stop the server
                print(f"Skipped chat {chat_id}: {type(err).__name__}. "
                      "If it's the demo bot, open it in Telegram and press Start.")

        @client.on(events.NewMessage())
        async def on_message(event):
            message = event.message
            if not is_watched(message.chat_id, watched) or not should_show(message, me.id):
                return
            chat = await event.get_chat()
            try:
                item = await to_inbox_item(message, chat_name=chat_title(chat, me.id), transcribe=transcribe)
            except Exception as err:  # keep serving on any single failure
                print(f"Could not process message {message.id}: {type(err).__name__}: {err}")
                return
            if item:
                inbox.add(item)
                asyncio.create_task(add_drafts(item))
                print(f"+ {item.kind:5} from {item.chat_name}: {item.text[:60]}")

        class TelegramSender:
            """Sends replies from your account, only when the glasses confirm."""

            async def send_text(self, chat_id, text, reply_to):
                await client.send_message(chat_id, text, reply_to=reply_to)
                print(f"> sent text to {chat_id}: {text[:60]}")

            async def send_voice(self, chat_id, ogg_path, reply_to):
                await client.send_file(chat_id, str(ogg_path), voice_note=True, reply_to=reply_to)
                print(f"> sent voice note to {chat_id}")

        quick = QuickReplyStore(SERVER_DIR / "quick_replies")
        replies = ReplyService(inbox=inbox, stt=local.transcribe_pcm, telegram=TelegramSender(),
                               watched=watched, tmp_dir=TMP, quick=quick)

        server = uvicorn.Server(uvicorn.Config(
            create_app(inbox, replies=replies, quick=quick, stt=local.transcribe_pcm, chats=chats, writer=writer), host="127.0.0.1", port=settings.port, log_level="warning",
        ))
        print(f"Inbox API on http://127.0.0.1:{settings.port}/inbox")
        try:
            await asyncio.gather(server.serve(), client.run_until_disconnected())
        finally:
            stop.set()


if __name__ == "__main__":
    asyncio.run(main())
