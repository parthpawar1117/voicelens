"""Voice commands spoken to the glasses, parsed locally (instant, no AI).

    "Send a message to Rahul: hi, how are you"  -> text  to Rahul
    "Tell Mom I will be late"                     -> text  to Mom
    "Send a voice note to Dev Team, deploying"    -> voice to Dev Team

Whisper already turned the speech into English text. The spoken name is then
matched against your chats; ambiguous names return every match so the
glasses can ask which one.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from typing import Literal

_WAKE = re.compile(r"^\s*(?:hey\s+)?voice\s?lens[,.!]?\s*", re.I)
_SEP = r"(?:\s*[:,\-]\s*|\s+saying\s+|\s+that\s+)"
_VOICE = re.compile(r"^(?:send\s+(?:a\s+)?)?voice\s?(?:note|message|memo)\s+to\s+(?P<rest>.+)$", re.I)
_TEXT = re.compile(r"^(?:send\s+(?:a\s+)?(?:message|text|msg)\s+to|message|text|tell)\s+(?P<rest>.+)$", re.I)


@dataclass(frozen=True)
class Command:
    kind: Literal["text", "voice"]
    contact: str
    text: str


def _split(rest: str) -> tuple[str, str] | None:
    m = re.match(rf"^(?P<who>.+?){_SEP}(?P<text>.+)$", rest, re.I)
    if m:
        who, text = m["who"], m["text"]
    else:  # no separator: the name is the first word ("Tell Rahul I will be late")
        parts = rest.split(None, 1)
        if len(parts) < 2:
            return None
        who, text = parts
    who = who.strip(" .,:;!?")
    text = text.strip()
    return (who, text) if who and text else None


def parse_command(said: str) -> Command | None:
    said = _WAKE.sub("", said or "").strip()
    for kind, pattern in (("voice", _VOICE), ("text", _TEXT)):
        m = pattern.match(said)
        if m and (parts := _split(m["rest"])):
            return Command(kind=kind, contact=parts[0], text=parts[1])
    return None


def _norm(name: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", name.lower()).split())


def resolve_contact(spoken: str, chats: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """Chats whose name matches the spoken name, best tier only."""
    s = _norm(spoken)
    if not s:
        return []
    exact = [c for c in chats if _norm(c[1]) == s]
    if exact:
        return exact
    words = s.split()
    prefix = [c for c in chats if all(any(t.startswith(w) for t in _norm(c[1]).split()) for w in words)]
    if prefix:
        return prefix
    scored = [(difflib.SequenceMatcher(None, s, _norm(c[1])).ratio(), c) for c in chats]
    best = max((r for r, _ in scored), default=0)
    return [c for r, c in scored if r >= 0.8 and r == best]
