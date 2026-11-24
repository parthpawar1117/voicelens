"""Local Whisper engine (not implemented yet)."""


class LocalWhisper:
    def __init__(self, model_factory=None):
        raise NotImplementedError

    async def __call__(self, audio_path: str) -> str:
        raise NotImplementedError
