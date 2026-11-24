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
