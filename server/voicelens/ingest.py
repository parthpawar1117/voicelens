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


async def backfill(history, inbox, *, chat_name: str, transcribe: Transcriber) -> int:
    """Add recent messages (given newest first, as Telegram returns them).

    Adds oldest first so the inbox ends up newest first. One failed voice note
    is skipped instead of stopping the whole backfill. Returns how many were added.
    """
    added = 0
    for message in reversed(list(history)):
        try:
            item = await to_inbox_item(message, chat_name=chat_name, transcribe=transcribe)
        except Exception:
            continue
        if item:
            inbox.add(item)
            added += 1
    return added


def should_show(message, my_id: int) -> bool:
    """Show what others send you. Your own messages only in Saved Messages,
    where testing happens; in a friend's chat your replies aren't incoming."""
    return not getattr(message, "out", False) or message.chat_id == my_id


def is_watched(chat_id: int, watched: set[int]) -> bool:
    return chat_id in watched


def load_watched(path: Path, my_id: int, extra: set[int] | frozenset[int] = frozenset()) -> set[int]:
    """Chat ids to watch from a JSON file {"chats": [id, ..., "me"]}.

    "me" means your Saved Messages. Without a file, only Saved Messages is
    watched, which is safe for testing. `extra` adds chats such as the demo-friend
    bot. A phone page will edit this file later.
    """
    try:
        chats = json.loads(Path(path).read_text(encoding="utf-8")).get("chats", [])
    except (OSError, json.JSONDecodeError):
        chats = ["me"]
    return {my_id if c == "me" else int(c) for c in chats} | set(extra)
