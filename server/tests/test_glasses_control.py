"""Dashboard glasses controls: which simulator inputs a click or key sends."""

import pytest

from devtools.dashboard import ALLOWED_ACTIONS, steps_to_open, validate_action


def test_only_real_g2_gestures_are_allowed():
    for action in ("up", "down", "click", "double_click"):
        assert validate_action(action) == action
    with pytest.raises(ValueError):
        validate_action("rm -rf")
    assert "long_press" in ALLOWED_ACTIONS  # needed for Day 3 replies


def test_jump_from_the_inbox_swipes_to_the_top_then_down_then_opens():
    # Never double tap on the inbox: there it means "exit".
    assert steps_to_open(index=2, total=5, screen="inbox") == ["up"] * 5 + ["down"] * 2 + ["click"]


def test_jump_from_an_open_message_first_goes_back_to_the_inbox():
    assert steps_to_open(index=0, total=3, screen="message") == ["double_click", "up", "up", "up", "click"]


@pytest.mark.parametrize("screen", ["recording", "thinking", "confirm", "error"])
def test_jump_from_a_reply_screen_backs_out_twice(screen):
    # One double tap: reply screen -> message (cancelling any draft); a second: message -> inbox.
    assert steps_to_open(index=0, total=1, screen=screen)[:2] == ["double_click", "double_click"]


def test_jump_rejects_a_row_that_does_not_exist():
    with pytest.raises(ValueError):
        steps_to_open(index=5, total=5, screen="inbox")


def test_jump_moves_only_the_needed_steps_when_the_selection_is_known():
    # Selected row 1, target row 4: three swipes down, not a trip to the top.
    assert steps_to_open(index=4, total=10, screen="inbox", current=1) == ["down"] * 3 + ["click"]
    assert steps_to_open(index=0, total=10, screen="inbox", current=2) == ["up"] * 2 + ["click"]


def test_jump_from_a_message_keeps_the_selection_and_moves_from_it():
    # Backing out of a message keeps that message selected in the inbox.
    assert steps_to_open(index=2, total=10, screen="message", current=2) == ["double_click", "click"]


def test_restart_command_relaunches_the_simulator_on_the_dev_server():
    from devtools.dashboard import simulator_command
    cmd = simulator_command()
    assert cmd[-1] == "http://localhost:5173"
    assert "--automation-port" in cmd and "9898" in cmd


def test_quick_reply_clip_path_is_only_inside_the_store(tmp_path, monkeypatch):
    from devtools import dashboard
    monkeypatch.setattr(dashboard, "QUICK_DIR", tmp_path)
    (tmp_path / "q3.ogg").write_bytes(b"OggS")
    assert dashboard.quick_clip("q3") == b"OggS"
    for bad in ("../.env", "q3.ogg", r"..\x", "q", "q3/../../x", ""):
        assert dashboard.quick_clip(bad) is None
    assert dashboard.quick_clip("q99") is None


def test_jump_backs_out_of_the_quick_list_twice():
    assert steps_to_open(index=0, total=1, screen="quick")[:2] == ["double_click", "double_click"]


def test_open_targets_the_message_and_retries_when_the_glasses_list_lags():
    from devtools.dashboard import open_message

    class FakeGlasses:
        """Glasses whose inbox lags one refresh behind the server."""
        def __init__(self):
            self.server_ids = [9, 8, 7]          # 9 just arrived
            self.glasses_ids = [8, 7]            # glasses haven't fetched it yet
            self.screen, self.sel, self.sent = "inbox", 8, []

        def status(self):
            return {"inbox": [{"id": i} for i in self.server_ids],
                    "ui": {"screen": self.screen, "selected_id": self.sel}}

        def send(self, action):
            self.sent.append(action)
            ids = self.glasses_ids
            if self.screen == "inbox":
                at = ids.index(self.sel) if self.sel in ids else 0
                if action == "up": self.sel = ids[max(0, at - 1)]
                elif action == "down": self.sel = ids[min(len(ids) - 1, at + 1)]
                elif action == "click": self.screen = "message"
            elif self.screen == "message" and action == "double_click":
                self.screen = "inbox"

        def sleep(self, _s):
            self.glasses_ids = list(self.server_ids)  # the glasses catch up on their next poll

    g = FakeGlasses()
    assert open_message(9, status=g.status, send=g.send, sleep=g.sleep) is True
    assert (g.screen, g.sel) == ("message", 9)


def test_open_gives_up_cleanly_if_the_message_never_appears():
    from devtools.dashboard import open_message
    st = {"inbox": [{"id": 1}], "ui": {"screen": "inbox", "selected_id": 1}}
    assert open_message(42, status=lambda: st, send=lambda a: None, sleep=lambda s: None) is False
