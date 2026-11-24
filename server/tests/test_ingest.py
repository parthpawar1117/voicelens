"""Turning Telegram messages from watched chats into inbox items."""

import json
from datetime import datetime, timezone
from types import SimpleNamespace

from voicelens.hybrid import HybridTranscript
from voicelens.ingest import is_watched, load_watched, to_inbox_item

WHEN = datetime(2026, 11, 25, 9, 30, tzinfo=timezone.utc)  # 15:00 IST


def msg(i=1, text="", voice=False, audio=False, duration=None):
    return SimpleNamespace(
        id=i, chat_id=555, message=text, voice=voice, audio=audio, date=WHEN,
        file=SimpleNamespace(duration=duration) if (voice or audio) else None,
    )


async def never_called(_message):
    raise AssertionError("text messages must not be transcribed")


async def fake_transcribe(_message):
    return HybridTranscript(text="Meeting moved to 5", source="local")


async def test_text_message_goes_straight_in_without_transcription():
    item = await to_inbox_item(msg(text="Where are you?"), chat_name="Mom", transcribe=never_called)
    assert (item.kind, item.text, item.chat_name, item.duration) == ("text", "Where are you?", "Mom", None)


async def test_voice_note_is_transcribed_and_keeps_its_length_and_engine():
    item = await to_inbox_item(msg(voice=True, duration=6), chat_name="Rahul", transcribe=fake_transcribe)
    assert (item.kind, item.text, item.duration, item.source) == ("voice", "Meeting moved to 5", 6, "local")


async def test_audio_files_are_treated_like_voice_notes():
    item = await to_inbox_item(msg(audio=True, duration=30), chat_name="Rahul", transcribe=fake_transcribe)
    assert item.kind == "voice"


async def test_stickers_photos_and_empty_messages_are_skipped():
    assert await to_inbox_item(msg(text=""), chat_name="Rahul", transcribe=never_called) is None


async def test_received_time_is_shown_in_india_time():
    item = await to_inbox_item(msg(text="hi"), chat_name="Mom", transcribe=never_called)
    assert item.received_at == "15:00"


def test_only_picked_chats_are_watched():
    assert is_watched(555, {555, 777})
    assert not is_watched(123, {555, 777})


def test_load_watched_reads_chat_ids_from_settings_file(tmp_path):
    path = tmp_path / "watched_chats.json"
    path.write_text(json.dumps({"chats": [555, "me"]}))
    assert load_watched(path, my_id=42) == {555, 42}


def test_load_watched_defaults_to_saved_messages_when_no_file(tmp_path):
    assert load_watched(tmp_path / "missing.json", my_id=42) == {42}


async def test_backfill_adds_recent_history_so_the_newest_ends_up_first():
    from voicelens.inbox import Inbox
    from voicelens.ingest import backfill

    history = [msg(i=3, text="newest"), msg(i=2, text="middle"), msg(i=1, text="oldest")]  # Telegram order
    inbox = Inbox()
    added = await backfill(history, inbox, chat_name="Mom", transcribe=never_called)
    assert added == 3
    assert [x.text for x in inbox.items()] == ["newest", "middle", "oldest"]


async def test_backfill_skips_media_it_cannot_show_and_keeps_going_after_a_failure():
    from voicelens.inbox import Inbox
    from voicelens.ingest import backfill

    async def flaky(_message):
        raise RuntimeError("transcription failed")

    history = [msg(i=3, text="hi"), msg(i=2, voice=True, duration=4), msg(i=1, text="")]
    inbox = Inbox()
    added = await backfill(history, inbox, chat_name="Mom", transcribe=flaky)
    assert added == 1
    assert [x.text for x in inbox.items()] == ["hi"]


def test_demo_friend_bot_chat_is_watched_automatically(tmp_path):
    assert load_watched(tmp_path / "missing.json", my_id=42, extra={777}) == {42, 777}


def test_your_own_replies_in_a_friends_chat_are_not_shown_as_incoming():
    from voicelens.ingest import should_show
    mine = SimpleNamespace(out=True, chat_id=777)
    theirs = SimpleNamespace(out=False, chat_id=777)
    saved = SimpleNamespace(out=True, chat_id=42)  # Saved Messages: everything is "yours"
    assert should_show(theirs, my_id=42)
    assert not should_show(mine, my_id=42)
    assert should_show(saved, my_id=42)
