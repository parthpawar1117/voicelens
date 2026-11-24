"""Local Whisper engine: decodes with our ffmpeg, loads the model once, joins text."""

import subprocess
from types import SimpleNamespace

import imageio_ffmpeg
import numpy as np

from voicelens.local_whisper import LocalWhisper, decode_to_16k_mono


class FakeModel:
    def __init__(self, texts):
        self.texts, self.inputs = texts, []

    def transcribe(self, audio, **kwargs):
        self.inputs.append((audio, kwargs))
        segments = (SimpleNamespace(text=t) for t in self.texts)
        return segments, SimpleNamespace(language="en")


def make(model, loads=None):
    def factory():
        if loads is not None:
            loads.append(1)
        return model

    return LocalWhisper(model_factory=factory, decoder=lambda path: f"decoded:{path}")


async def test_joins_segment_text_and_trims_whitespace():
    engine = make(FakeModel([" Meeting moved", " to 5 pm. "]))
    assert await engine("/tmp/a.ogg") == "Meeting moved to 5 pm."


async def test_model_receives_decoded_audio_not_the_file_path():
    model = FakeModel(["hi"])
    await make(model)("/tmp/a.ogg")
    assert model.inputs[0][0] == "decoded:/tmp/a.ogg"


async def test_model_is_loaded_lazily_and_only_once():
    loads = []
    engine = make(FakeModel(["hi"]), loads)
    assert loads == []
    await engine("/tmp/a.ogg")
    await engine("/tmp/b.ogg")
    assert loads == [1]


async def test_lets_whisper_detect_the_language_for_hinglish():
    model = FakeModel(["kal meeting hai"])
    await make(model)("/tmp/a.ogg")
    assert model.inputs[0][1].get("language") is None


async def test_empty_audio_gives_empty_string():
    assert await make(FakeModel([]))("/tmp/a.ogg") == ""


def test_decoder_turns_an_ogg_opus_file_into_16k_float_samples(tmp_path):
    # Build a real 1-second Telegram-style voice file (OGG Opus) with our ffmpeg.
    ogg = tmp_path / "tone.ogg"
    subprocess.run(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-loglevel", "error", "-f", "lavfi",
         "-i", "sine=frequency=440:duration=1", "-c:a", "libopus", str(ogg)],
        check=True,
    )
    samples = decode_to_16k_mono(str(ogg))
    assert samples.dtype == np.float32
    assert 15000 < len(samples) < 17000
    assert 0 < np.abs(samples).max() <= 1.0


async def test_translates_to_english_so_hindi_shows_in_latin_letters():
    # G2 has one firmware font and drops unsupported characters; Whisper writes
    # Hindi in Devanagari. Translate mode always yields English (Latin script).
    model = FakeModel(["Bring the laptop"])
    await make(model)("/tmp/a.ogg")
    assert model.inputs[0][1].get("task") == "translate"


def test_default_model_is_small_for_better_hinglish():
    from voicelens.local_whisper import DEFAULT_MODEL
    assert DEFAULT_MODEL == "small"


async def test_warm_up_loads_model_and_runs_one_transcription_on_silence():
    # The first real transcription was ~2.7x slower than later ones (VAD model
    # and engine initialise lazily), so run one pass on silence at startup.
    model = FakeModel([])
    engine = LocalWhisper(model_factory=lambda: model, decoder=lambda p: p)
    await engine.warm_up()
    assert len(model.inputs) == 1
    audio, kwargs = model.inputs[0]
    assert isinstance(audio, np.ndarray) and len(audio) >= 16000
    assert not audio.any()  # pure silence
    assert kwargs.get("task") == "translate"


async def test_records_decode_and_model_time_of_the_last_call():
    engine = make(FakeModel(["hi"]))
    await engine("/tmp/a.ogg")
    timings = engine.last_timings
    assert set(timings) == {"decode_s", "model_s", "thread_wait_s"}
    assert all(v >= 0 for v in timings.values())


def test_uses_gpu_with_float16_when_cuda_is_available():
    from voicelens.local_whisper import pick_device
    assert pick_device(cuda_devices=1) == ("cuda", "float16")


def test_uses_cpu_with_int8_without_a_gpu():
    from voicelens.local_whisper import pick_device
    assert pick_device(cuda_devices=0) == ("cpu", "int8")


def test_falls_back_to_cpu_when_gpu_model_fails_to_load():
    from voicelens.local_whisper import load_model

    calls = []

    def fake_whisper(size, device, compute_type):
        calls.append(device)
        if device == "cuda":
            raise RuntimeError("Library cublas64_12.dll is not found")
        return f"model-{device}"

    model, device = load_model("small", cuda_devices=1, whisper_cls=fake_whisper)
    assert (model, device) == ("model-cpu", "cpu")
    assert calls == ["cuda", "cpu"]


async def test_keep_alive_pings_the_model_until_stopped():
    # After ~20 s idle the GPU clocks down and the next note took 1.36 s instead
    # of 0.28 s; a tiny inference every 2 s brought it to 0.46 s.
    import asyncio
    model = FakeModel([])
    engine = make(model)
    stop = asyncio.Event()
    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 3:
            stop.set()

    await engine.keep_alive(interval=2.0, stop=stop, sleep=fake_sleep)
    assert len(model.inputs) == 3
    assert sleeps == [2.0, 2.0, 2.0]
    assert all(len(audio) <= 1600 for audio, _ in model.inputs)  # tiny: 0.1 s


async def test_keep_alive_skips_a_ping_while_a_real_note_is_running():
    import asyncio
    model = FakeModel([])
    engine = make(model)
    engine._busy = 1  # a real transcription is in progress
    stop = asyncio.Event()

    async def fake_sleep(seconds):
        stop.set()

    await engine.keep_alive(interval=2.0, stop=stop, sleep=fake_sleep)
    assert model.inputs == []
