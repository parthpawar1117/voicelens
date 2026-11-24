"""Quick replies: short replies saved once (text + your own voice), sent silently."""

import pytest

from voicelens.quick_replies import DEFAULTS, MAX_LABEL, QuickReplyStore


def test_starts_with_text_only_defaults_so_it_works_on_day_one(tmp_path):
    store = QuickReplyStore(tmp_path)
    labels = [q.label for q in store.list()]
    assert labels == list(DEFAULTS)
    assert all(not q.has_voice for q in store.list())


def test_add_with_voice_saves_the_clip_and_survives_a_restart(tmp_path):
    store = QuickReplyStore(tmp_path)
    q = store.add("On my way, 5 minutes", ogg=b"OggS-fake-audio", duration=1.8)
    assert q.has_voice and q.duration == 1.8
    reloaded = QuickReplyStore(tmp_path)
    again = reloaded.get(q.id)
    assert again.label == "On my way, 5 minutes"
    assert reloaded.voice_path(q.id).read_bytes() == b"OggS-fake-audio"


def test_new_replies_go_to_the_top(tmp_path):
    store = QuickReplyStore(tmp_path)
    q = store.add("Call you at 6")
    assert store.list()[0].id == q.id


def test_delete_removes_the_entry_and_its_clip(tmp_path):
    store = QuickReplyStore(tmp_path)
    q = store.add("Bye", ogg=b"OggS")
    path = store.voice_path(q.id)
    store.delete(q.id)
    assert store.get(q.id) is None
    assert not path.exists()


def test_label_is_trimmed_and_validated(tmp_path):
    store = QuickReplyStore(tmp_path)
    assert store.add("  Yes, done  ").label == "Yes, done"
    with pytest.raises(ValueError):
        store.add("   ")
    with pytest.raises(ValueError):
        store.add("x" * (MAX_LABEL + 1))


def test_only_plain_ascii_labels_so_the_g2_font_can_draw_them(tmp_path):
    store = QuickReplyStore(tmp_path)
    assert store.add("On my way 🚗").label == "On my way"
    assert store.add("Café “soon”").label == 'Cafe "soon"'


def test_ids_are_not_reused_after_a_delete(tmp_path):
    store = QuickReplyStore(tmp_path)
    a = store.add("A")
    store.delete(a.id)
    b = store.add("B")
    assert b.id != a.id


def test_unknown_id(tmp_path):
    store = QuickReplyStore(tmp_path)
    assert store.get("nope") is None
    store.delete("nope")  # no error
