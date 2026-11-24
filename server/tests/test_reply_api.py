"""Reply endpoints the glasses app calls."""

import base64

from fastapi.testclient import TestClient

from voicelens.app import create_app
from voicelens.inbox import Inbox, InboxItem
from voicelens.reply import ReplyService


class FakeTelegram:
    def __init__(self):
        self.sent = []

    async def send_text(self, chat_id, text, reply_to):
        self.sent.append(("text", text))

    async def send_voice(self, chat_id, ogg_path, reply_to):
        self.sent.append(("voice", ogg_path.suffix))


async def stt(_pcm):
    return "On my way"


def client(tmp_path):
    inbox = Inbox()
    inbox.add(InboxItem(id=10, chat_id=555, chat_name="Mom", kind="voice", text="Where?",
                        duration=3, received_at="21:00"))
    tg = FakeTelegram()
    svc = ReplyService(inbox=inbox, stt=stt, telegram=tg, watched={555}, tmp_dir=tmp_path)
    return TestClient(create_app(inbox, replies=svc)), tg


AUDIO = base64.b64encode(b"\x10\x00" * 16000).decode()


def test_prepare_then_send(tmp_path):
    c, tg = client(tmp_path)
    r = c.post("/reply/prepare", json={"item_id": 10, "audio_b64": AUDIO})
    assert r.status_code == 200
    d = r.json()
    assert d["text"] == "On my way" and d["format"] == "voice" and d["chat_name"] == "Mom"
    assert tg.sent == []
    assert c.post("/reply/send", json={"draft_id": d["draft_id"], "format": "voice"}).json()["sent"] is True
    assert tg.sent == [("voice", ".ogg")]


def test_cancel_means_nothing_is_sent(tmp_path):
    c, tg = client(tmp_path)
    d = c.post("/reply/prepare", json={"item_id": 10, "audio_b64": AUDIO}).json()
    assert c.post("/reply/cancel", json={"draft_id": d["draft_id"]}).status_code == 200
    assert c.post("/reply/send", json={"draft_id": d["draft_id"], "format": "text"}).status_code == 404
    assert tg.sent == []


def test_bad_audio_and_unknown_message_give_clear_errors(tmp_path):
    c, _ = client(tmp_path)
    assert c.post("/reply/prepare", json={"item_id": 10, "audio_b64": "!!!"}).status_code == 400
    assert c.post("/reply/prepare", json={"item_id": 99, "audio_b64": AUDIO}).status_code == 404


def test_replies_are_off_when_the_server_has_no_telegram(tmp_path):
    c = TestClient(create_app(Inbox()))
    assert c.post("/reply/prepare", json={"item_id": 1, "audio_b64": AUDIO}).status_code == 503
