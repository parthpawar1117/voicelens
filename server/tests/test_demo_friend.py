"""Demo friend: a Telegram bot that plays the person messaging you in demos."""

import json

import pytest

from devtools.demo_friend import DemoFriend, bot_id_from_token, parse_replies


class FakeBotApi:
    """Records Bot API calls and returns canned results."""

    def __init__(self, results=None):
        self.calls = []
        self.results = results or {}

    def __call__(self, method, data=None, files=None):
        self.calls.append((method, data, files))
        return self.results.get(method, {"ok": True, "result": {}})


def test_bot_id_is_the_number_before_the_colon():
    assert bot_id_from_token("123456789:AAHxyz") == 123456789
    with pytest.raises(ValueError):
        bot_id_from_token("not-a-token")


def test_sends_text_to_your_chat():
    api = FakeBotApi()
    DemoFriend(api, chat_id=42).send_text("Where are you?")
    assert api.calls == [("sendMessage", {"chat_id": 42, "text": "Where are you?"}, None)]


def test_sends_a_voice_note_file():
    api = FakeBotApi()
    DemoFriend(api, chat_id=42).send_voice(b"OggS-bytes")
    method, data, files = api.calls[0]
    assert method == "sendVoice" and data == {"chat_id": 42}
    assert files["voice"][1] == b"OggS-bytes"


def test_needs_you_to_press_start_first():
    with pytest.raises(RuntimeError, match="Start"):
        DemoFriend(FakeBotApi(), chat_id=None).send_text("hi")


def test_parses_your_replies_and_finds_your_chat():
    updates = [
        {"update_id": 1, "message": {"message_id": 5, "chat": {"id": 42}, "from": {"id": 42}, "text": "/start", "date": 1}},
        {"update_id": 2, "message": {"message_id": 6, "chat": {"id": 42}, "from": {"id": 42}, "text": "10 minutes", "date": 2,
                                      "reply_to_message": {"message_id": 3}}},
        {"update_id": 3, "message": {"message_id": 7, "chat": {"id": 42}, "from": {"id": 42}, "date": 3,
                                      "voice": {"file_id": "F1", "duration": 2}}},
    ]
    replies, chat_id, next_offset = parse_replies(updates)
    assert chat_id == 42
    assert next_offset == 4
    assert replies == [
        {"id": 6, "kind": "text", "text": "10 minutes", "file_id": None, "duration": None, "date": 2},
        {"id": 7, "kind": "voice", "text": None, "file_id": "F1", "duration": 2, "date": 3},
    ]


def test_no_updates_keeps_the_offset():
    assert parse_replies([], offset=9) == ([], None, 9)


def test_browser_webm_recording_becomes_a_telegram_voice_file():
    import subprocess
    import imageio_ffmpeg
    from devtools.demo_friend import to_ogg_opus

    ff = imageio_ffmpeg.get_ffmpeg_exe()
    webm = subprocess.run([ff, "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=300:duration=1",
                           "-c:a", "libopus", "-f", "webm", "-"], capture_output=True, check=True).stdout
    ogg = to_ogg_opus(webm)
    assert ogg[:4] == b"OggS"
    probe = subprocess.run([ff, "-hide_banner", "-f", "ogg", "-i", "-"], input=ogg, capture_output=True).stderr.decode()
    assert "opus" in probe


def test_empty_browser_recording_is_rejected():
    from devtools.demo_friend import to_ogg_opus
    with pytest.raises(ValueError):
        to_ogg_opus(b"")


def test_token_with_a_space_inside_is_rejected_without_showing_it():
    from devtools.demo_friend import clean_token
    with pytest.raises(ValueError) as err:
        clean_token("123456:ABC def")
    assert "ABC" not in str(err.value) and "def" not in str(err.value)


def test_token_surrounding_spaces_and_quotes_are_trimmed():
    from devtools.demo_friend import clean_token
    assert clean_token('  "123456:ABCdef"  ') == "123456:ABCdef"


def test_bot_api_errors_never_include_the_token(monkeypatch):
    import urllib.request
    from devtools.demo_friend import BotApiError, make_bot_api

    def boom(req, timeout=0):
        raise OSError(f"failed for {req.full_url}")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    api = make_bot_api("123456:SECRETTOKEN")
    with pytest.raises(BotApiError) as err:
        api("getMe")
    assert "SECRETTOKEN" not in str(err.value)
    assert "getMe" in str(err.value)
