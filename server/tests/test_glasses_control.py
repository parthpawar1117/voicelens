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
