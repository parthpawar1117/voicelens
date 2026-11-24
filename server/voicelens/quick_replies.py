"""Quick replies: short replies you save once and send silently from the glasses.

Each one has a text label and, optionally, a clip of your own voice (OGG Opus,
Telegram's voice-note format). When the friend sent a voice note and the quick
reply has a clip, they get your real voice; otherwise they get the text.

Stored on your machine in server/quick_replies/ (gitignored: personal voice):
    index.json   {"next": 5, "items": [{"id", "label", "duration", "has_voice"}]}
    q3.ogg       the clip for quick reply q3
"""

from __future__ import annotations

import json
import re
import threading
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path

DEFAULTS = (
    "Can't talk now, I'll call you back",
    "On my way",
    "Give me 10 minutes",
    "Yes, done",
)
MAX_LABEL = 64

_ASCII_PUNCT = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'",
                              "–": "-", "—": "-", "…": "..."})


def to_g2_text(text: str) -> str:
    """Plain ASCII: the G2 firmware font drops characters it doesn't have."""
    text = unicodedata.normalize("NFKD", text.translate(_ASCII_PUNCT))
    text = text.encode("ascii", "ignore").decode()
    text = " ".join(text.split())
    return re.sub(r" +([,.!?;:])", r"\1", text)  # "meeting 🙏, call" -> "meeting, call"


@dataclass(frozen=True)
class QuickReply:
    id: str
    label: str
    duration: float | None = None
    has_voice: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


class QuickReplyStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._index = self.root / "index.json"
        self._lock = threading.Lock()
        if self._index.exists():
            data = json.loads(self._index.read_text(encoding="utf-8"))
            self._next = data["next"]
            self._items = [QuickReply(**i) for i in data["items"]]
        else:
            self._next = 1
            self._items = []
            for label in DEFAULTS:
                self._items.append(QuickReply(id=self._new_id(), label=label))
            self._save()

    def _new_id(self) -> str:
        qid = f"q{self._next}"
        self._next += 1
        return qid

    def _save(self) -> None:
        tmp = self._index.with_suffix(".tmp")
        tmp.write_text(json.dumps({"next": self._next, "items": [i.to_dict() for i in self._items]}, indent=2),
                       encoding="utf-8")
        tmp.replace(self._index)

    def voice_path(self, qid: str) -> Path:
        return self.root / f"{qid}.ogg"

    def list(self) -> list[QuickReply]:
        with self._lock:
            return list(self._items)

    def get(self, qid: str) -> QuickReply | None:
        with self._lock:
            return next((i for i in self._items if i.id == qid), None)

    def add(self, label: str, *, ogg: bytes | None = None, duration: float | None = None) -> QuickReply:
        label = to_g2_text(label)
        if not label:
            raise ValueError("A quick reply needs some text")
        if len(label) > MAX_LABEL:
            raise ValueError(f"Keep quick replies under {MAX_LABEL} characters so they fit on the glasses")
        with self._lock:
            q = QuickReply(id=self._new_id(), label=label, duration=duration, has_voice=ogg is not None)
            if ogg is not None:
                self.voice_path(q.id).write_bytes(ogg)
            self._items.insert(0, q)
            self._save()
            return q

    def delete(self, qid: str) -> None:
        with self._lock:
            self._items = [i for i in self._items if i.id != qid]
            self.voice_path(qid).unlink(missing_ok=True)
            self._save()
