"""Brief features: pick chats, digest, AI drafts, approve a draft, voice commands."""

import base64
import json

import pytest
from fastapi.testclient import TestClient

from voicelens.app import create_app
from voicelens.chats import ChatDirectory
from voicelens.inbox import Inbox, InboxItem
from voicelens.reply import NotAllowed, ReplyService

PCM = b"\x10\x00" * 16000


class FakeTelegram:
    def __init__(self):
        self.sent = []

    async def send_text(self, chat_id, text, reply_to):
        self.sent.append(("text", chat_id, text, reply_to))

    async def send_voice(self, chat_id, ogg_path, reply_to):
        self.sent.append(("voice", chat_id, ogg_path.suffix, reply_to))


class FakeWriter:
    def __init__(self):
        self.digest_calls = []

    async def draft_replies(self, chat_name, recent, incoming):
        return ["Yes, on it", "Give me 5 min"]

    async def digest(self, chats):
        self.digest_calls.append(chats)
        return ["BTC broke 100k", "Deploy at 6 pm"]


def directory(tmp_path, picked=(10,)):
    d = ChatDirectory(tmp_path / "watched_chats.json", my_id=99)
    d.set_known([(10, "Rahul Sharma", "user"), (20, "Crypto Alpha", "channel"), (30, "Mom", "user"), (99, "Saved Messages", "user")])
    for c in picked:
        d.pick(c, True)
    return d


def item(i=1, chat_id=10, name="Rahul Sharma", text="Are you coming?", kind="text"):
    return InboxItem(id=i, chat_id=chat_id, chat_name=name, kind=kind, text=text, duration=None, received_at="21:00")


# ---- chat picking ----

def test_picks_are_saved_and_survive_a_restart(tmp_path):
    d = directory(tmp_path, picked=(10, 20))
    assert d.is_watched(20) and not d.is_watched(30)
    d.pick(20, False)
    again = ChatDirectory(tmp_path / "watched_chats.json", my_id=99)
    assert again.is_watched(10) and not again.is_watched(20)


def test_watched_set_is_live_so_the_server_sees_changes_immediately(tmp_path):
    d = directory(tmp_path)
    live = d.watched
    d.pick(30, True)
    assert 30 in live


def test_saved_messages_is_watched_by_default(tmp_path):
    assert ChatDirectory(tmp_path / "none.json", my_id=99).is_watched(99)


# ---- AI drafts on inbox items ----

def test_inbox_attaches_drafts_to_an_item():
    inbox = Inbox()
    inbox.add(item())
    inbox.attach_drafts(10, 1, ["Yes, on it", "Later"])
    assert inbox.get(1).drafts == ("Yes, on it", "Later")
    assert inbox.items()[0].to_dict()["drafts"] == ["Yes, on it", "Later"]


# ---- approve an AI draft ----

async def test_approving_a_draft_sends_that_text_after_the_countdown(tmp_path):
    inbox, tg = Inbox(), FakeTelegram()
    inbox.add(item())
    svc = ReplyService(inbox=inbox, stt=None, telegram=tg, watched={10}, tmp_dir=tmp_path)
    draft = await svc.prepare_text(item_id=1, text="Yes, on it")
    assert (draft.format, draft.voice_available) == ("text", False)
    assert tg.sent == []
    await svc.send(draft.id, fmt="text")
    assert tg.sent == [("text", 10, "Yes, on it", 1)]


# ---- voice commands ----

async def stt_says(text):
    async def stt(_pcm):
        return text
    return stt


async def test_command_to_a_known_contact_becomes_a_new_message_draft(tmp_path):
    tg = FakeTelegram()
    svc = ReplyService(inbox=Inbox(), stt=await stt_says("Send a message to Mom: reached safely"),
                       telegram=tg, watched=set(), tmp_dir=tmp_path)
    result = await svc.prepare_command(pcm=PCM, chats=directory(tmp_path).known)
    draft = result["draft"]
    assert (draft.chat_id, draft.chat_name, draft.text, draft.format) == (30, "Mom", "reached safely", "text")
    await svc.send(draft.id, fmt="text")
    assert tg.sent == [("text", 30, "reached safely", None)]  # a new message, not a reply


async def test_voice_note_command_sends_your_recording(tmp_path):
    tg = FakeTelegram()
    svc = ReplyService(inbox=Inbox(), stt=await stt_says("Voice note to Rahul, running late"),
                       telegram=tg, watched=set(), tmp_dir=tmp_path)
    result = await svc.prepare_command(pcm=PCM, chats=directory(tmp_path).known)
    assert result["draft"].format == "voice"
    await svc.send(result["draft"].id, fmt="voice")
    assert tg.sent == [("voice", 10, ".ogg", None)]


async def test_unknown_contact_or_non_command_explains_what_went_wrong(tmp_path):
    svc = ReplyService(inbox=Inbox(), stt=await stt_says("Tell Priya hello"), telegram=FakeTelegram(),
                       watched=set(), tmp_dir=tmp_path)
    assert "Priya" in (await svc.prepare_command(pcm=PCM, chats=directory(tmp_path).known))["error"]
    svc2 = ReplyService(inbox=Inbox(), stt=await stt_says("what time is it"), telegram=FakeTelegram(),
                        watched=set(), tmp_dir=tmp_path)
    assert "Say" in (await svc2.prepare_command(pcm=PCM, chats=directory(tmp_path).known))["error"]


# ---- API ----

def client(tmp_path, writer=None):
    inbox, tg = Inbox(), FakeTelegram()
    inbox.add(item(1, 10, "Rahul Sharma", "Are you coming?"))
    inbox.add(item(2, 20, "Crypto Alpha", "BTC just broke 100k", kind="text"))
    chats = directory(tmp_path, picked=(10, 20))

    async def stt(_pcm):
        return "Tell Mom I'm on my way"

    svc = ReplyService(inbox=inbox, stt=stt, telegram=tg, watched=chats.watched, tmp_dir=tmp_path)
    return TestClient(create_app(inbox, replies=svc, chats=chats, writer=writer)), tg, chats


def test_chat_list_shows_kind_and_picked_and_picking_works(tmp_path):
    c, _, chats = client(tmp_path)
    rows = {r["id"]: r for r in c.get("/chats").json()["chats"]}
    assert rows[20] == {"id": 20, "name": "Crypto Alpha", "kind": "channel", "picked": True}
    assert rows[30]["picked"] is False
    assert c.post("/chats/pick", json={"chat_id": 30, "picked": True}).status_code == 200
    assert chats.is_watched(30)


def test_digest_summarises_picked_chats_and_is_cached(tmp_path):
    w = FakeWriter()
    c, _, _ = client(tmp_path, writer=w)
    body = c.get("/digest").json()
    assert body["lines"] == ["BTC broke 100k", "Deploy at 6 pm"]
    assert set(w.digest_calls[0]) == {"Rahul Sharma", "Crypto Alpha"}
    c.get("/digest")
    assert len(w.digest_calls) == 1  # cached


def test_digest_says_when_ai_is_off(tmp_path):
    c, _, _ = client(tmp_path, writer=None)
    assert c.get("/digest").json() == {"lines": [], "error": "Add ANTHROPIC_API_KEY to server/.env for digests"}


def test_approve_draft_and_command_endpoints(tmp_path):
    c, tg, _ = client(tmp_path)
    d = c.post("/reply/text", json={"item_id": 1, "text": "Yes, on it"}).json()
    assert d["format"] == "text" and d["voice_available"] is False and d["text"] == "Yes, on it"
    cmd = c.post("/command/prepare", json={"audio_b64": base64.b64encode(PCM).decode()}).json()
    assert cmd["chat_name"] == "Mom" and cmd["text"] == "I'm on my way" and cmd["format"] == "text"
    assert tg.sent == []
