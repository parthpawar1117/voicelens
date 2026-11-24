"""Turn Telegram messages from watched chats into inbox items.

Text goes straight in (nothing to wait for). Voice notes and audio files are
transcribed first by the hybrid engine. Other media is skipped for now.
"""

from __future__ import annotations

import json
from datetime import timedelta, timezone
from pathlib import Path
from typing import Awaitable, Callable

from voicelens.hybrid import HybridTranscript
from voicelens.inbox import InboxItem

IST = timezone(timedelta(hours=5, minutes=30))

Transcriber = Callable[[object], Awaitable[HybridTranscript]]


async def to_inbox_item(message, *, chat_name: str, transcribe: Transcriber) -> InboxItem | None:
    received_at = message.date.astimezone(IST).strftime("%H:%M")
    common = dict(id=message.id, chat_id=message.chat_id, chat_name=chat_name, received_at=received_at)

    if message.voice or message.audio:
        result = await transcribe(message)
        return InboxItem(
            **common, kind="voice", text=result.text,
            duration=getattr(message.file, "duration", None), source=result.source,
        )

    text = (message.message or "").strip()
    if text:
        return InboxItem(**common, kind="text", text=text, duration=None)
    return None


def is_watched(chat_id: int, watched: set[int]) -> bool:
    return chat_id in watched


def load_watched(path: Path, my_id: int) -> set[int]:
    """Chat ids to watch from a JSON file {"chats": [id, ..., "me"]}.

    "me" means your Saved Messages. Without a file, only Saved Messages is
    watched, which is safe for testing. A phone page will edit this file later.
    """
    try:
        chats = json.loads(Path(path).read_text(encoding="utf-8")).get("chats", [])
    except (OSError, json.JSONDecodeError):
        chats = ["me"]
    return {my_id if c == "me" else int(c) for c in chats}
