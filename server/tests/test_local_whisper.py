"""Local Whisper engine: loads the model once, lazily, and joins segment text."""

from types import SimpleNamespace

from voicelens.local_whisper import LocalWhisper


class FakeModel:
    def __init__(self, texts):
        self.texts, self.paths = texts, []

    def transcribe(self, path, **kwargs):
        self.paths.append((path, kwargs))
        segments = (SimpleNamespace(text=t) for t in self.texts)
        return segments, SimpleNamespace(language="en")


async def test_joins_segment_text_and_trims_whitespace():
    model = FakeModel([" Meeting moved", " to 5 pm. "])
    engine = LocalWhisper(model_factory=lambda: model)
    assert await engine("/tmp/a.ogg") == "Meeting moved to 5 pm."


async def test_model_is_loaded_lazily_and_only_once():
    loads = []

    def factory():
        loads.append(1)
        return FakeModel(["hi"])

    engine = LocalWhisper(model_factory=factory)
    assert loads == []
    await engine("/tmp/a.ogg")
    await engine("/tmp/b.ogg")
    assert loads == [1]


async def test_lets_whisper_detect_the_language_for_hinglish():
    model = FakeModel(["kal meeting hai"])
    await LocalWhisper(model_factory=lambda: model)("/tmp/a.ogg")
    _, kwargs = model.paths[0]
    assert kwargs.get("language") is None


async def test_empty_audio_gives_empty_string():
    assert await LocalWhisper(model_factory=lambda: FakeModel([]))("/tmp/a.ogg") == ""
