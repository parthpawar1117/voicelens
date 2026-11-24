"""Inbox: one list of voice notes and texts from watched chats, newest first."""

from voicelens.inbox import Inbox, InboxItem


def item(i, kind="text", chat="Rahul", text="hi", duration=None):
    return InboxItem(id=i, chat_id=100, chat_name=chat, kind=kind, text=text,
                     duration=duration, received_at=f"21:0{i}")


def test_newest_item_comes_first():
    inbox = Inbox()
    inbox.add(item(1))
    inbox.add(item(2))
    assert [x.id for x in inbox.items()] == [2, 1]


def test_holds_both_voice_notes_and_texts():
    inbox = Inbox()
    inbox.add(item(1, kind="voice", text="Meeting at 5", duration=6))
    inbox.add(item(2, kind="text", text="Where are you?"))
    kinds = [x.kind for x in inbox.items()]
    assert kinds == ["text", "voice"]


def test_same_message_is_not_added_twice():
    inbox = Inbox()
    inbox.add(item(1))
    inbox.add(item(1))
    assert len(inbox.items()) == 1


def test_keeps_only_the_newest_items():
    inbox = Inbox(limit=3)
    for i in range(1, 6):
        inbox.add(item(i))
    assert [x.id for x in inbox.items()] == [5, 4, 3]


def test_get_returns_one_item_or_none():
    inbox = Inbox()
    inbox.add(item(7, text="full text here"))
    assert inbox.get(7).text == "full text here"
    assert inbox.get(99) is None


def test_items_serialise_for_the_glasses_app():
    data = item(3, kind="voice", text="Bring the laptop", duration=4).to_dict()
    assert data == {
        "id": 3, "chat_id": 100, "chat_name": "Rahul", "kind": "voice",
        "text": "Bring the laptop", "duration": 4, "received_at": "21:03",
        "source": None, "language": None,
    }
