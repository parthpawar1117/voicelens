"""Shared inbox: voice notes and texts from watched chats, newest first.

Kept in memory only (no message text is written to disk). Thread-safe so the
Telegram handler and the HTTP API can use it at the same time.
"""

from __future__ import annotations

import threading
from dataclasses import asdict, dataclass, replace
from typing import Literal


@dataclass(frozen=True)
class InboxItem:
    id: int
    chat_id: int
    chat_name: str
    kind: Literal["voice", "text"]
    text: str
    duration: float | None
    received_at: str
    source: str | None = None      # "telegram" / "local" for voice notes
    language: str | None = None    # detected language of a voice note
    drafts: tuple[str, ...] = ()   # AI-drafted replies, filled in shortly after arrival

    def to_dict(self) -> dict:
        d = asdict(self)
        d["drafts"] = list(self.drafts)
        return d


class Inbox:
    def __init__(self, limit: int = 50):
        self._limit = limit
        self._items: list[InboxItem] = []
        self._lock = threading.Lock()

    def add(self, item: InboxItem) -> None:
        with self._lock:
            if any(x.id == item.id and x.chat_id == item.chat_id for x in self._items):
                return
            self._items = [item, *self._items][: self._limit]

    def items(self) -> list[InboxItem]:
        with self._lock:
            return list(self._items)

    def attach_drafts(self, chat_id: int, item_id: int, drafts: list[str]) -> None:
        with self._lock:
            self._items = [replace(x, drafts=tuple(drafts)) if (x.id, x.chat_id) == (item_id, chat_id) else x
                           for x in self._items]

    def get(self, item_id: int) -> InboxItem | None:
        with self._lock:
            return next((x for x in self._items if x.id == item_id), None)
