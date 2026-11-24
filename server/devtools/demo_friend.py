"""Demo friend: a Telegram bot that plays the person messaging you.

For demo videos only. Your real account and the glasses are unchanged: the
bot is just another chat ("Rahul (demo)"), so judges see two sides: what
"Rahul" sends, and the reply that comes back from your glasses.

Setup: create a bot with @BotFather, put TELEGRAM_DEMO_BOT_TOKEN in
server/.env, then press Start in the bot's chat (bots can't message first).
"""

from __future__ import annotations

import json
import mimetypes
import threading
import uuid
import urllib.request
from typing import Callable

API = "https://api.telegram.org"

BotCall = Callable[..., dict]


def bot_id_from_token(token: str) -> int:
    head = token.split(":", 1)[0]
    if ":" not in token or not head.isdigit():
        raise ValueError("That doesn't look like a bot token (expected 123456:ABC...)")
    return int(head)


def parse_replies(updates: list[dict], offset: int | None = None) -> tuple[list[dict], int | None, int | None]:
    """Your messages to the bot -> (replies, your chat id, next getUpdates offset)."""
    replies, chat_id = [], None
    for u in updates:
        offset = u["update_id"] + 1
        m = u.get("message")
        if not m:
            continue
        chat_id = m["chat"]["id"]
        if (m.get("text") or "").startswith("/start"):
            continue
        voice = m.get("voice") or m.get("audio")
        replies.append({
            "id": m["message_id"],
            "kind": "voice" if voice else "text",
            "text": m.get("text") if not voice else None,
            "file_id": voice["file_id"] if voice else None,
            "duration": voice.get("duration") if voice else None,
            "date": m.get("date"),
        })
    return replies, chat_id, offset


def make_bot_api(token: str) -> BotCall:
    """Call the Bot API with the standard library (JSON or multipart upload)."""

    def call(method: str, data: dict | None = None, files: dict | None = None, timeout: float = 35) -> dict:
        url = f"{API}/bot{token}/{method}"
        if files:
            boundary = uuid.uuid4().hex
            parts = []
            for k, v in (data or {}).items():
                parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
            for field, (name, content) in files.items():
                ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
                parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; filename="{name}"\r\n'
                             f"Content-Type: {ctype}\r\n\r\n".encode() + content + b"\r\n")
            body = b"".join(parts) + f"--{boundary}--\r\n".encode()
            req = urllib.request.Request(url, data=body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        else:
            req = urllib.request.Request(url, data=json.dumps(data or {}).encode(),
                                         headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())

    return call


class DemoFriend:
    def __init__(self, api: BotCall, chat_id: int | None):
        self.api = api
        self.chat_id = chat_id
        self.conversation: list[dict] = []  # newest last: what "Rahul" sees
        self._offset: int | None = None
        self._lock = threading.Lock()

    def _need_chat(self) -> int:
        if self.chat_id is None:
            raise RuntimeError("Open the bot in Telegram and press Start first")
        return self.chat_id

    def send_text(self, text: str) -> None:
        self.api("sendMessage", {"chat_id": self._need_chat(), "text": text})
        self._log({"from": "friend", "kind": "text", "text": text})

    def send_voice(self, ogg: bytes) -> None:
        self.api("sendVoice", {"chat_id": self._need_chat()}, files={"voice": ("voice.ogg", ogg)})
        self._log({"from": "friend", "kind": "voice", "text": None})

    def poll_once(self, timeout: int = 25) -> list[dict]:
        """Fetch your replies (long poll). Also learns your chat id from /start."""
        res = self.api("getUpdates", {"offset": self._offset, "timeout": timeout, "allowed_updates": ["message"]})
        replies, chat_id, self._offset = parse_replies(res.get("result", []), self._offset)
        if chat_id is not None:
            self.chat_id = chat_id
        for r in replies:
            self._log({"from": "you", **r})
        return replies

    def file_bytes(self, token: str, file_id: str) -> bytes:
        path = self.api("getFile", {"file_id": file_id})["result"]["file_path"]
        with urllib.request.urlopen(f"{API}/file/bot{token}/{path}", timeout=20) as r:
            return r.read()

    def _log(self, entry: dict) -> None:
        with self._lock:
            self.conversation = [*self.conversation, entry][-30:]
