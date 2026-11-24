"""Replies from the glasses.

Rule: the reply matches what the friend sent (voice note -> voice note,
text -> text); a swipe during the countdown switches it. Your speech is
always transcribed for the on-glasses preview; for a voice reply the audio
itself is converted to OGG Opus, the format Telegram uses for voice notes.
"""

from __future__ import annotations

import subprocess
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import imageio_ffmpeg

Format = Literal["voice", "text"]
SAMPLE_RATE = 16_000


def default_format(kind: str) -> Format:
    if kind not in ("voice", "text"):
        raise ValueError(f"can't reply to a {kind!r} message")
    return kind  # type: ignore[return-value]


def toggle_format(fmt: Format) -> Format:
    return "text" if fmt == "voice" else "voice"


class DraftNotFound(LookupError):
    pass


class NotAllowed(PermissionError):
    """The chat isn't one the user picked for VoiceLens."""


@dataclass
class Draft:
    id: str
    item_id: int
    chat_id: int
    chat_name: str
    format: Format
    text: str
    pcm: bytes = field(repr=False)


class ReplyService:
    """Recording -> draft with a preview -> sent only when the glasses say so.

    The 3-second undo lives on the glasses: they call send() only after the
    countdown, or cancel() on a double tap. A draft is sent at most once.
    """

    def __init__(self, *, inbox, stt, telegram, watched: set[int], tmp_dir: Path | None = None):
        self._inbox, self._stt, self._tg, self._watched = inbox, stt, telegram, watched
        self._tmp = Path(tmp_dir) if tmp_dir else Path(tempfile.gettempdir())
        self._drafts: dict[str, Draft] = {}

    async def prepare(self, *, item_id: int, pcm: bytes) -> Draft:
        item = self._inbox.get(item_id)
        if item is None:
            raise DraftNotFound(f"message {item_id} is not in the inbox")
        if item.chat_id not in self._watched:
            raise NotAllowed("replies only go to chats you picked")
        text = (await self._stt(pcm)).strip()
        if not text:
            raise ValueError("didn't catch any speech, try again")
        draft = Draft(id=uuid.uuid4().hex[:12], item_id=item.id, chat_id=item.chat_id,
                      chat_name=item.chat_name, format=default_format(item.kind), text=text, pcm=pcm)
        self._drafts[draft.id] = draft
        return draft

    async def send(self, draft_id: str, *, fmt: Format) -> Draft:
        draft = self._drafts.pop(draft_id, None)  # pop first: at most one send
        if draft is None:
            raise DraftNotFound("draft already sent, cancelled or unknown")
        if fmt == "voice":
            ogg = pcm_to_ogg_opus(draft.pcm, self._tmp / f"reply_{draft.id}.ogg")
            try:
                await self._tg.send_voice(draft.chat_id, ogg, reply_to=draft.item_id)
            finally:
                ogg.unlink(missing_ok=True)
        else:
            await self._tg.send_text(draft.chat_id, draft.text, reply_to=draft.item_id)
        draft.format = fmt
        return draft

    def cancel(self, draft_id: str) -> None:
        self._drafts.pop(draft_id, None)


def pcm_to_ogg_opus(pcm: bytes, path: Path) -> Path:
    """G2 mic audio (16 kHz mono s16le) -> OGG Opus voice-note file."""
    if not pcm:
        raise ValueError("empty recording")
    path = Path(path)
    subprocess.run(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error",
         "-f", "s16le", "-ar", str(SAMPLE_RATE), "-ac", "1", "-i", "-",
         "-c:a", "libopus", "-b:a", "32k", "-application", "voip", str(path)],
        input=pcm, check=True, capture_output=True,
    )
    return path
