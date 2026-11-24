"""Local Whisper engine (faster-whisper) for users without Telegram Premium.

Runs on the user's own machine: audio is not sent to any third-party service.
The model is loaded on first use (download ~480 MB for "small" on first run),
on the NVIDIA GPU when available (0.2 s per short note) or the CPU (~3 s), and
kept in memory. Language is auto-detected and the output is translated to
English, because the G2 firmware font may drop Devanagari characters. On real
notes, "small" + translate turned Hinglish into accurate English; English
notes come out unchanged.

Audio is decoded with the ffmpeg bundled by imageio-ffmpeg, not PyAV: current
PyAV releases dropped an option faster-whisper 1.1 passes to av.open().
"""

from __future__ import annotations

import asyncio
import subprocess
import threading
import time
from typing import Awaitable, Callable

import imageio_ffmpeg
import numpy as np

DEFAULT_MODEL = "small"
SAMPLE_RATE = 16_000


def decode_to_16k_mono(audio_path: str) -> np.ndarray:
    """Decode any audio file to 16 kHz mono float32 in [-1, 1], as Whisper expects."""
    raw = subprocess.run(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-loglevel", "error", "-i", audio_path,
         "-f", "s16le", "-ac", "1", "-ar", str(SAMPLE_RATE), "-"],
        check=True, capture_output=True,
    ).stdout
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def pick_device(cuda_devices: int) -> tuple[str, str]:
    """GPU with float16 when CUDA is visible, else CPU with int8.

    Measured on an RTX 4050 laptop: "small" took 0.17-0.25 s per short note on
    the GPU versus ~3.1 s on the CPU, with identical text.
    """
    return ("cuda", "float16") if cuda_devices > 0 else ("cpu", "int8")


def _add_nvidia_dll_dirs() -> None:
    """Let ctranslate2 find cuBLAS/cuDNN installed as pip wheels (Windows)."""
    import os
    import sysconfig
    from pathlib import Path

    root = Path(sysconfig.get_paths()["purelib"]) / "nvidia"
    for bin_dir in root.glob("*/bin"):
        if hasattr(os, "add_dll_directory"):
            os.add_dll_directory(str(bin_dir))
        os.environ["PATH"] = f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"


def _probe(model) -> None:
    # Missing CUDA libraries only fail on the first inference, not on load.
    if hasattr(model, "transcribe"):
        segments, _ = model.transcribe(np.zeros(SAMPLE_RATE // 2, dtype=np.float32), beam_size=1)
        list(segments)


def load_model(size: str, cuda_devices: int | None = None, whisper_cls=None):
    """Return (model, device). Tries the GPU first and falls back to the CPU."""
    if whisper_cls is None:
        _add_nvidia_dll_dirs()
        from faster_whisper import WhisperModel  # heavy import, only when needed

        whisper_cls = WhisperModel
    if cuda_devices is None:
        import ctranslate2

        cuda_devices = ctranslate2.get_cuda_device_count()

    device, compute_type = pick_device(cuda_devices)
    if device == "cuda":
        try:
            model = whisper_cls(size, device="cuda", compute_type=compute_type)
            _probe(model)
            return model, "cuda"
        except Exception:  # missing DLLs, out of GPU memory, driver issues
            pass
    return whisper_cls(size, device="cpu", compute_type="int8"), "cpu"


loaded_device: str | None = None


def _default_factory(model_size: str = DEFAULT_MODEL):
    global loaded_device
    model, loaded_device = load_model(model_size)
    return model


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
        self.last_timings: dict[str, float] = {}
        self._busy = 0

    def _get_model(self):
        with self._lock:
            if self._model is None:
                self._model = self._factory()
            return self._model

    def _run(self, audio) -> str:
        segments, _info = self._get_model().transcribe(
            audio, language=None, task="translate", beam_size=1, vad_filter=True,
        )
        return " ".join(s.text.strip() for s in segments).strip()

    def _transcribe_sync(self, audio_path: str, queued_at: float) -> str:
        started = time.perf_counter()
        audio = self._decode(audio_path)
        decoded = time.perf_counter()
        text = self._run(audio)
        self.last_timings = {
            "thread_wait_s": round(started - queued_at, 3),  # time before a worker thread picked it up
            "decode_s": round(decoded - started, 3),
            "model_s": round(time.perf_counter() - decoded, 3),
        }
        return text

    async def warm_up(self) -> None:
        """Load the model and run one pass on 1 s of silence.

        Measured on a real 4 s note: 8.7 s for the first transcription after
        loading versus 3.2 s afterwards, because the VAD model and inference
        engine initialise lazily. Paying that at startup keeps notes fast.
        """
        silence = np.zeros(SAMPLE_RATE, dtype=np.float32)
        await asyncio.to_thread(self._run, silence)

    def _ping(self) -> None:
        # VAD off so the model really runs on the GPU instead of skipping silence.
        tiny = np.zeros(SAMPLE_RATE // 10, dtype=np.float32)  # 0.1 s
        segments, _ = self._get_model().transcribe(tiny, beam_size=1, vad_filter=False)
        list(segments)

    async def keep_alive(
        self,
        interval: float = 2.0,
        *,
        stop: asyncio.Event,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        """Run a tiny inference every `interval` seconds until `stop` is set.

        The GPU clocks down when idle: after 20 s idle a note took 1.36 s of
        model time versus 0.28 s back-to-back; pinging every 2 s gave 0.46 s.
        Run it only while the app is in use. Skips a ping while a note runs.
        """
        while not stop.is_set():
            if self._busy == 0:
                await asyncio.to_thread(self._ping)
            await sleep(interval)

    async def __call__(self, audio_path: str) -> str:
        # Whisper is CPU-bound; keep the event loop free for Telegram updates.
        self._busy += 1
        try:
            return await asyncio.to_thread(self._transcribe_sync, audio_path, time.perf_counter())
        finally:
            self._busy -= 1
