"""Local Whisper engine (faster-whisper) for users without Telegram Premium.

Runs on the user's own machine: audio is not sent to any third-party service.
The model is loaded on first use (download ~145 MB for "base" on first run) and
kept in memory. Language is auto-detected so Hindi/Hinglish notes work.

Audio is decoded with the ffmpeg bundled by imageio-ffmpeg, not PyAV: current
PyAV releases dropped an option faster-whisper 1.1 passes to av.open().
"""

from __future__ import annotations

import asyncio
import subprocess
import threading
from typing import Callable

import imageio_ffmpeg
import numpy as np

DEFAULT_MODEL = "base"
SAMPLE_RATE = 16_000


def decode_to_16k_mono(audio_path: str) -> np.ndarray:
    """Decode any audio file to 16 kHz mono float32 in [-1, 1], as Whisper expects."""
    raw = subprocess.run(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-loglevel", "error", "-i", audio_path,
         "-f", "s16le", "-ac", "1", "-ar", str(SAMPLE_RATE), "-"],
        check=True, capture_output=True,
    ).stdout
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def _default_factory(model_size: str = DEFAULT_MODEL):
    from faster_whisper import WhisperModel  # heavy import, only when needed

    # int8 on CPU keeps memory near 0.5 GB for "base".
    return WhisperModel(model_size, device="cpu", compute_type="int8")


class LocalWhisper:
    def __init__(
        self,
        model_factory: Callable[[], object] | None = None,
        decoder: Callable[[str], object] = decode_to_16k_mono,
    ):
        self._factory = model_factory or _default_factory
        self._decode = decoder
        self._model = None
        self._lock = threading.Lock()

    def _get_model(self):
        with self._lock:
            if self._model is None:
                self._model = self._factory()
            return self._model

    def _transcribe_sync(self, audio_path: str) -> str:
        audio = self._decode(audio_path)
        segments, _info = self._get_model().transcribe(
            audio, language=None, beam_size=1, vad_filter=True,
        )
        return " ".join(s.text.strip() for s in segments).strip()

    async def __call__(self, audio_path: str) -> str:
        # Whisper is CPU-bound; keep the event loop free for Telegram updates.
        return await asyncio.to_thread(self._transcribe_sync, audio_path)
