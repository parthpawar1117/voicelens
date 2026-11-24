"""The glasses app reports what it is showing so the dashboard can follow it."""

from fastapi.testclient import TestClient

from voicelens.app import create_app
from voicelens.inbox import Inbox


def test_ui_state_starts_unknown():
    assert TestClient(create_app(Inbox())).get("/ui-state").json() == {"screen": None, "selected_id": None, "page": 0}


def test_glasses_app_can_report_its_screen():
    c = TestClient(create_app(Inbox()))
    r = c.post("/ui-state", json={"screen": "message", "selected_id": 2190, "page": 1})
    assert r.status_code == 200
    assert c.get("/ui-state").json() == {"screen": "message", "selected_id": 2190, "page": 1}


def test_unknown_screen_names_are_rejected():
    c = TestClient(create_app(Inbox()))
    assert c.post("/ui-state", json={"screen": "hacked", "selected_id": None, "page": 0}).status_code == 422


def test_reply_screens_are_reported_too():
    c = TestClient(create_app(Inbox()))
    for screen in ("recording", "thinking", "confirm", "sending", "sent", "error"):
        assert c.post("/ui-state", json={"screen": screen, "selected_id": 1, "page": 0}).status_code == 200
