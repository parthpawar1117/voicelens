"""Voice commands: "send a message to Rahul: hi how are you" -> who, what, how."""

import pytest

from voicelens.commands import Command, parse_command, resolve_contact

CHATS = [(1, "Rahul Sharma"), (2, "Mom"), (3, "Dev Team"), (4, "Crypto Alpha Desk"), (5, "Rahul K")]


@pytest.mark.parametrize("said, kind, who, text", [
    ("Send a message to Rahul, hi how are you?", "text", "Rahul", "hi how are you?"),
    ("send message to mom: I'm coming home", "text", "mom", "I'm coming home"),
    ("Message Dev Team that the build is green.", "text", "Dev Team", "the build is green."),
    ("Text Mom saying dinner at 8", "text", "Mom", "dinner at 8"),
    ("Tell Rahul I will be late", "text", "Rahul", "I will be late"),
    ("Send a voice note to Mom: reached safely", "voice", "Mom", "reached safely"),
    ("Voice note to Dev Team, deploying now", "voice", "Dev Team", "deploying now"),
    ("VoiceLens, send a message to Rahul hi", "text", "Rahul", "hi"),
])
def test_parses_who_what_and_how(said, kind, who, text):
    cmd = parse_command(said)
    assert cmd == Command(kind=kind, contact=who, text=text)


@pytest.mark.parametrize("said", ["What is the weather", "", "send", "Hello there"])
def test_non_commands_are_ignored(said):
    assert parse_command(said) is None


def test_resolves_a_spoken_name_to_one_chat():
    assert resolve_contact("mom", CHATS) == [(2, "Mom")]
    assert resolve_contact("dev team", CHATS) == [(3, "Dev Team")]
    assert resolve_contact("crypto alpha", CHATS) == [(4, "Crypto Alpha Desk")]
    assert resolve_contact("Rahool Sharma", CHATS) == [(1, "Rahul Sharma")]  # Whisper misspelling


def test_ambiguous_names_return_every_match_for_the_user_to_choose():
    assert {c for c, _ in resolve_contact("Rahul", CHATS)} == {1, 5}


def test_unknown_name_returns_nothing():
    assert resolve_contact("Priya", CHATS) == []
