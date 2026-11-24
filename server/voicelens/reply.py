"""Replies from the glasses.

Rule: the reply matches what the friend sent (voice note -> voice note,
text -> text); a swipe during the countdown switches it. Your speech is
always transcribed for the on-glasses preview; for a voice reply the audio
itself is converted to OGG Opus, the format Telegram uses for voice notes.
"""

from __future__ import annotations

import subprocess
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
