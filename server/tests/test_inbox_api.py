"""HTTP API the G2 app polls for the inbox."""

from fastapi.testclient import TestClient

from voicelens.app import create_app
from voicelens.inbox import Inbox, InboxItem


def client_with(*items):
    inbox = Inbox()
    for it in items:
        inbox.add(it)
    return TestClient(create_app(inbox))


def it(i, kind="text", text="hi"):
    return InboxItem(id=i, chat_id=1, chat_name="Rahul", kind=kind, text=text,
                     duration=6 if kind == "voice" else None, received_at="21:00")


def test_inbox_lists_items_newest_first_with_a_count():
    r = client_with(it(1), it(2, kind="voice", text="Meeting at 5")).get("/inbox")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 2
    assert [x["id"] for x in body["items"]] == [2, 1]
    assert body["items"][0]["kind"] == "voice"


def test_empty_inbox():
    assert client_with().get("/inbox").json() == {"count": 0, "items": []}


def test_single_item_by_id():
    r = client_with(it(7, text="full text")).get("/inbox/7")
    assert r.status_code == 200
    assert r.json()["text"] == "full text"


def test_unknown_item_is_404():
    assert client_with().get("/inbox/99").status_code == 404


def test_cors_allows_the_g2_dev_server():
    r = client_with().get("/inbox", headers={"Origin": "http://localhost:5173"})
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"
