"""Quick reply API: list/add/delete for the dashboard, send for the glasses."""

import base64
import subprocess

import imageio_ffmpeg
from fastapi.testclient import TestClient

from voicelens.app import create_app
from voicelens.inbox import Inbox, InboxItem
from voicelens.quick_replies import QuickReplyStore
from voicelens.reply import ReplyService


class FakeTelegram:
    def __init__(self):
        self.sent = []

    async def send_text(self, chat_id, text, reply_to):
        self.sent.append(("text", text))

    async def send_voice(self, chat_id, ogg_path, reply_to):
        self.sent.append(("voice", ogg_path.read_bytes()[:4]))


async def stt(pcm):
    return "Call you at six" if pcm else ""


def make(tmp_path, kind="voice"):
    inbox = Inbox()
    inbox.add(InboxItem(id=10, chat_id=555, chat_name="Mom", kind=kind, text="Where?", duration=3, received_at="21:00"))
    store = QuickReplyStore(tmp_path / "quick")
    tg = FakeTelegram()
    svc = ReplyService(inbox=inbox, stt=stt, telegram=tg, watched={555}, tmp_dir=tmp_path, quick=store)
    return TestClient(create_app(inbox, replies=svc, quick=store, stt=stt)), tg, store


def browser_recording(seconds=1.0) -> str:
    """A WebM/Opus clip like Chrome's MediaRecorder makes, base64."""
    webm = subprocess.run(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-loglevel", "error", "-f", "lavfi",
         "-i", f"sine=frequency=300:duration={seconds}", "-c:a", "libopus", "-f", "webm", "-"],
        capture_output=True, check=True).stdout
    return base64.b64encode(webm).decode()


def test_lists_the_starter_replies(tmp_path):
    c, _, _ = make(tmp_path)
    items = c.get("/quick-replies").json()["items"]
    assert len(items) == 4 and items[0]["label"] == "Can't talk now, I'll call you back"
    assert items[0]["has_voice"] is False


def test_add_a_typed_reply(tmp_path):
    c, _, _ = make(tmp_path)
    r = c.post("/quick-replies", json={"label": "In a meeting"})
    assert r.status_code == 200 and r.json()["label"] == "In a meeting"


def test_add_a_recorded_reply_whisper_writes_the_label_and_it_becomes_a_voice_note(tmp_path):
    c, _, store = make(tmp_path)
    r = c.post("/quick-replies", json={"audio_b64": browser_recording(1.0)})
    assert r.status_code == 200
    q = r.json()
    assert q["label"] == "Call you at six" and q["has_voice"] is True
    assert 0.8 < q["duration"] < 1.3
    assert store.voice_path(q["id"]).read_bytes()[:4] == b"OggS"  # Telegram voice format


def test_a_typed_label_wins_over_the_transcript(tmp_path):
    c, _, _ = make(tmp_path)
    q = c.post("/quick-replies", json={"label": "Calling at 6", "audio_b64": browser_recording()}).json()
    assert q["label"] == "Calling at 6" and q["has_voice"] is True


def test_bad_input_gives_clear_errors(tmp_path):
    c, _, _ = make(tmp_path)
    assert c.post("/quick-replies", json={}).status_code == 422
    assert c.post("/quick-replies", json={"label": "   "}).status_code == 422
    assert c.post("/quick-replies", json={"audio_b64": "!!!"}).status_code == 400


def test_delete(tmp_path):
    c, _, _ = make(tmp_path)
    qid = c.get("/quick-replies").json()["items"][0]["id"]
    assert c.delete(f"/quick-replies/{qid}").status_code == 200
    assert qid not in [i["id"] for i in c.get("/quick-replies").json()["items"]]


def test_send_a_recorded_quick_reply_to_a_voice_note(tmp_path):
    c, tg, _ = make(tmp_path, kind="voice")
    qid = c.post("/quick-replies", json={"label": "On my way", "audio_b64": browser_recording()}).json()["id"]
    d = c.post("/reply/quick", json={"item_id": 10, "quick_id": qid}).json()
    assert d["format"] == "voice" and d["voice_available"] is True and d["text"] == "On my way"
    assert tg.sent == []  # nothing before the countdown
    assert c.post("/reply/send", json={"draft_id": d["draft_id"], "format": "voice"}).json()["sent"] is True
    assert tg.sent == [("voice", b"OggS")]


def test_text_only_quick_reply_reports_no_voice(tmp_path):
    c, _, _ = make(tmp_path, kind="voice")
    qid = c.get("/quick-replies").json()["items"][0]["id"]
    d = c.post("/reply/quick", json={"item_id": 10, "quick_id": qid}).json()
    assert d["format"] == "text" and d["voice_available"] is False


def test_spoken_reply_preview_also_says_voice_is_available(tmp_path):
    c, _, _ = make(tmp_path)
    pcm = base64.b64encode(b"\x10\x00" * 16000).decode()
    assert c.post("/reply/prepare", json={"item_id": 10, "audio_b64": pcm}).json()["voice_available"] is True


def test_quick_replies_off_without_a_store(tmp_path):
    c = TestClient(create_app(Inbox()))
    assert c.get("/quick-replies").status_code == 503
