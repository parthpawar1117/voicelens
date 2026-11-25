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
    item_id: int | None  # None = a new message (voice command), not a reply
    chat_id: int
    chat_name: str
    format: Format
    text: str
    pcm: bytes = field(default=b"", repr=False)
    voice_clip: Path | None = None  # a saved quick-reply clip, reused as-is
    voice_available: bool = True    # False for text-only quick replies


class ReplyService:
    """Recording -> draft with a preview -> sent only when the glasses say so.

    The 5-second undo lives on the glasses: they call send() only after the
    countdown, or cancel() on a double tap. A draft is sent at most once.
    Quick replies use the same flow with your saved text and voice clip, so
    they need no speech at all.
    """

    def __init__(self, *, inbox, stt, telegram, watched: set[int], tmp_dir: Path | None = None, quick=None):
        self._inbox, self._stt, self._tg, self._watched = inbox, stt, telegram, watched
        self._quick = quick
        self._tmp = Path(tmp_dir) if tmp_dir else Path(tempfile.gettempdir())
        self._drafts: dict[str, Draft] = {}

    def _target(self, item_id: int):
        item = self._inbox.get(item_id)
        if item is None:
            raise DraftNotFound(f"message {item_id} is not in the inbox")
        if item.chat_id not in self._watched:
            raise NotAllowed("replies only go to chats you picked")
        return item

    async def prepare_quick(self, *, item_id: int, quick_id: str) -> Draft:
        item = self._target(item_id)
        q = self._quick.get(quick_id) if self._quick else None
        if q is None:
            raise DraftNotFound("that quick reply no longer exists")
        fmt = default_format(item.kind) if q.has_voice else "text"
        draft = Draft(id=uuid.uuid4().hex[:12], item_id=item.id, chat_id=item.chat_id,
                      chat_name=item.chat_name, format=fmt, text=q.label,
                      voice_clip=self._quick.voice_path(q.id) if q.has_voice else None,
                      voice_available=q.has_voice)
        self._drafts[draft.id] = draft
        return draft

    def _store(self, draft: Draft) -> Draft:
        self._drafts[draft.id] = draft
        return draft

    async def prepare_text(self, *, item_id: int, text: str) -> Draft:
        """Approve an AI-drafted reply: sent as text after the countdown."""
        item = self._target(item_id)
        text = text.strip()
        if not text:
            raise ValueError("that draft is empty")
        return self._store(Draft(id=uuid.uuid4().hex[:12], item_id=item.id, chat_id=item.chat_id,
                                 chat_name=item.chat_name, format="text", text=text, voice_available=False))

    async def prepare_command(self, *, pcm: bytes, chats: list[tuple[int, str]]) -> dict:
        """'Send a message to Mom: ...' -> a draft for a new message, or an error to show."""
        from voicelens.commands import parse_command, resolve_contact

        said = (await self._stt(pcm)).strip()
        cmd = parse_command(said)
        if cmd is None:
            return {"error": f'Heard "{said or "nothing"}". Say: send a message to <name>: <text>'}
        matches = resolve_contact(cmd.contact, chats)
        if not matches:
            return {"error": f'No chat called "{cmd.contact}"'}
        if len(matches) > 1:
            names = ", ".join(n for _, n in matches[:3])
            return {"error": f'"{cmd.contact}" matches {names}. Say the full name'}
        chat_id, chat_name = matches[0]
        return {"draft": self._store(Draft(id=uuid.uuid4().hex[:12], item_id=None, chat_id=chat_id,
                                           chat_name=chat_name, format=cmd.kind, text=cmd.text, pcm=pcm))}

    async def prepare(self, *, item_id: int, pcm: bytes) -> Draft:
        item = self._target(item_id)
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
        if fmt == "voice" and not draft.voice_available:
            fmt = "text"  # a text-only quick reply has no clip to send
        if fmt == "voice" and draft.voice_clip is not None:
            await self._tg.send_voice(draft.chat_id, draft.voice_clip, reply_to=draft.item_id)
        elif fmt == "voice":
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


def any_audio_to_pcm(audio: bytes) -> bytes:
    """Any recording (browser WebM, OGG, WAV...) -> 16 kHz mono s16le PCM."""
    if not audio:
        raise ValueError("empty recording")
    return subprocess.run(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-loglevel", "error", "-i", "-", "-vn",
         "-f", "s16le", "-ar", str(SAMPLE_RATE), "-ac", "1", "-"],
        input=audio, check=True, capture_output=True,
    ).stdout


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
