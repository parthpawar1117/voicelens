"""ReplyService: recording -> draft (preview) -> send after the countdown."""

import numpy as np
import pytest

from voicelens.inbox import Inbox, InboxItem
from voicelens.reply import DraftNotFound, NotAllowed, ReplyService

PCM = (np.ones(16000) * 1000).astype("<i2").tobytes()  # 1 s


def inbox_with(kind="text", chat_id=555):
    inbox = Inbox()
    inbox.add(InboxItem(id=10, chat_id=chat_id, chat_name="Mom", kind=kind, text="Where are you?",
                        duration=None, received_at="21:00"))
    return inbox


class FakeTelegram:
    def __init__(self):
        self.sent = []

    async def send_text(self, chat_id, text, reply_to):
        self.sent.append(("text", chat_id, text, reply_to))

    async def send_voice(self, chat_id, ogg_path, reply_to):
        assert ogg_path.exists()
        self.sent.append(("voice", chat_id, ogg_path.suffix, reply_to))


async def fake_stt(pcm):
    assert pcm == PCM
    return "Ten minutes, almost home."


def service(kind="text", watched=(555,), tmp_path=None):
    tg = FakeTelegram()
    svc = ReplyService(inbox=inbox_with(kind), stt=fake_stt, telegram=tg,
                       watched=set(watched), tmp_dir=tmp_path)
    return svc, tg


async def test_prepare_gives_a_preview_in_the_matching_format(tmp_path):
    svc, tg = service("text", tmp_path=tmp_path)
    draft = await svc.prepare(item_id=10, pcm=PCM)
    assert draft.text == "Ten minutes, almost home."
    assert draft.format == "text"
    assert draft.chat_name == "Mom"
    assert tg.sent == []  # nothing goes out before the countdown


async def test_voice_note_gets_a_voice_reply_by_default(tmp_path):
    svc, _ = service("voice", tmp_path=tmp_path)
    assert (await svc.prepare(item_id=10, pcm=PCM)).format == "voice"


async def test_send_text_reply_goes_to_the_same_chat_as_a_reply(tmp_path):
    svc, tg = service("text", tmp_path=tmp_path)
    draft = await svc.prepare(item_id=10, pcm=PCM)
    await svc.send(draft.id, fmt="text")
    assert tg.sent == [("text", 555, "Ten minutes, almost home.", 10)]


async def test_switching_to_voice_sends_an_ogg_voice_note(tmp_path):
    svc, tg = service("text", tmp_path=tmp_path)
    draft = await svc.prepare(item_id=10, pcm=PCM)
    await svc.send(draft.id, fmt="voice")
    assert tg.sent == [("voice", 555, ".ogg", 10)]


async def test_a_draft_can_be_sent_only_once(tmp_path):
    svc, tg = service("text", tmp_path=tmp_path)
    draft = await svc.prepare(item_id=10, pcm=PCM)
    await svc.send(draft.id, fmt="text")
    with pytest.raises(DraftNotFound):
        await svc.send(draft.id, fmt="text")
    assert len(tg.sent) == 1


async def test_cancel_throws_the_draft_away(tmp_path):
    svc, tg = service("text", tmp_path=tmp_path)
    draft = await svc.prepare(item_id=10, pcm=PCM)
    svc.cancel(draft.id)
    with pytest.raises(DraftNotFound):
        await svc.send(draft.id, fmt="text")
    assert tg.sent == []


async def test_never_sends_to_a_chat_you_did_not_pick(tmp_path):
    svc, tg = service("text", watched=(999,), tmp_path=tmp_path)
    with pytest.raises(NotAllowed):
        await svc.prepare(item_id=10, pcm=PCM)
    assert tg.sent == []


async def test_unknown_message_or_empty_speech_is_rejected(tmp_path):
    svc, _ = service("text", tmp_path=tmp_path)
    with pytest.raises(DraftNotFound):
        await svc.prepare(item_id=404, pcm=PCM)

    async def silent(_pcm):
        return ""

    svc2 = ReplyService(inbox=inbox_with(), stt=silent, telegram=FakeTelegram(), watched={555}, tmp_dir=tmp_path)
    with pytest.raises(ValueError):
        await svc2.prepare(item_id=10, pcm=PCM)


# ---- quick replies: no speech, your saved text + voice clip ----

from voicelens.quick_replies import QuickReplyStore


def quick_service(kind, tmp_path):
    tg = FakeTelegram()
    store = QuickReplyStore(tmp_path / "quick")
    svc = ReplyService(inbox=inbox_with(kind), stt=fake_stt, telegram=tg, watched={555},
                       tmp_dir=tmp_path, quick=store)
    return svc, tg, store


async def test_quick_reply_to_a_voice_note_defaults_to_your_saved_voice(tmp_path):
    svc, tg, store = quick_service("voice", tmp_path)
    q = store.add("On my way", ogg=b"OggS-my-voice", duration=1.2)
    draft = await svc.prepare_quick(item_id=10, quick_id=q.id)
    assert (draft.text, draft.format, draft.voice_available) == ("On my way", "voice", True)
    await svc.send(draft.id, fmt="voice")
    assert tg.sent == [("voice", 555, ".ogg", 10)]
    assert store.voice_path(q.id).exists()  # the saved clip is reused, never deleted


async def test_quick_reply_to_a_text_defaults_to_text(tmp_path):
    svc, tg, store = quick_service("text", tmp_path)
    q = store.add("On my way", ogg=b"OggS")
    draft = await svc.prepare_quick(item_id=10, quick_id=q.id)
    assert draft.format == "text"
    await svc.send(draft.id, fmt="text")
    assert tg.sent == [("text", 555, "On my way", 10)]


async def test_text_only_quick_reply_always_goes_as_text(tmp_path):
    svc, tg, store = quick_service("voice", tmp_path)
    q = store.list()[0]  # a starter reply, no recording
    draft = await svc.prepare_quick(item_id=10, quick_id=q.id)
    assert (draft.format, draft.voice_available) == ("text", False)
    await svc.send(draft.id, fmt="voice")  # asked for voice, but there is no clip
    assert tg.sent == [("text", 555, q.label, 10)]


async def test_quick_reply_never_needs_speech_recognition(tmp_path):
    async def stt_must_not_run(_pcm):
        raise AssertionError("quick replies are silent")
    store = QuickReplyStore(tmp_path / "quick")
    svc = ReplyService(inbox=inbox_with("text"), stt=stt_must_not_run, telegram=FakeTelegram(),
                       watched={555}, tmp_dir=tmp_path, quick=store)
    await svc.prepare_quick(item_id=10, quick_id=store.list()[0].id)


async def test_quick_reply_respects_picked_chats_and_unknown_ids(tmp_path):
    store = QuickReplyStore(tmp_path / "quick")
    svc = ReplyService(inbox=inbox_with("text"), stt=fake_stt, telegram=FakeTelegram(),
                       watched={999}, tmp_dir=tmp_path, quick=store)
    with pytest.raises(NotAllowed):
        await svc.prepare_quick(item_id=10, quick_id=store.list()[0].id)
    svc2, _, _ = quick_service("text", tmp_path / "b")
    with pytest.raises(DraftNotFound):
        await svc2.prepare_quick(item_id=10, quick_id="q999")


async def test_spoken_drafts_report_voice_available(tmp_path):
    svc, _ = service("text", tmp_path=tmp_path)
    assert (await svc.prepare(item_id=10, pcm=PCM)).voice_available is True
