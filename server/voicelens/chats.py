"""Your chats and which ones VoiceLens watches ("only the chats you pick").

`watched` is one live set shared with the server and the reply service, so a
pick on the dashboard takes effect immediately. Picks are saved to
server/watched_chats.json (gitignored). Saved Messages is watched until you
pick something else, so a fresh install works out of the box.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path


class ChatDirectory:
    def __init__(self, path: Path, my_id: int):
        self._path = Path(path)
        self._my_id = my_id
        self._lock = threading.Lock()
        self.known: list[tuple[int, str]] = []
        self._kinds: dict[int, str] = {}
        self.watched: set[int] = set()
        try:
            chats = json.loads(self._path.read_text(encoding="utf-8")).get("chats", [])
        except (OSError, json.JSONDecodeError):
            chats = ["me"]
        self.watched.update(my_id if c == "me" else int(c) for c in chats)

    def set_known(self, chats: list[tuple[int, str, str]]) -> None:
        """All your chats as (id, name, kind) with kind in user/group/channel."""
        with self._lock:
            self.known = [(cid, name) for cid, name, _ in chats]
            self._kinds = {cid: kind for cid, _, kind in chats}

    def is_watched(self, chat_id: int) -> bool:
        return chat_id in self.watched

    def pick(self, chat_id: int, picked: bool) -> None:
        with self._lock:
            (self.watched.add if picked else self.watched.discard)(chat_id)
            chats = ["me" if c == self._my_id else c for c in sorted(self.watched)]
            self._path.write_text(json.dumps({"chats": chats}, indent=2), encoding="utf-8")

    def listing(self) -> list[dict]:
        with self._lock:
            return [{"id": cid, "name": name, "kind": self._kinds.get(cid, "user"), "picked": cid in self.watched}
                    for cid, name in self.known]
