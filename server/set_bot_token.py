"""Save the demo bot's newest token from @BotFather into server/.env.

Run it yourself (it handles a secret):
    server\\.venv\\Scripts\\python server\\set_bot_token.py

- Reads the newest messages in your @BotFather chat with your Telegram login.
- Picks the token for the demo bot (the one in TELEGRAM_DEMO_BOT_TOKEN, or the
  bot id you pass: set_bot_token.py 9278152065).
- Writes it to server/.env, changing only that one line.
- Never prints the token.

It uses a temporary copy of your session. Telegram then sends new-message
updates to this connection instead of the server's, so restart server/run.py
afterwards (seen in testing: the server stopped receiving messages).
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import load_dotenv  # noqa: E402
from telethon import TelegramClient  # noqa: E402

from devtools.demo_friend import clean_token, extract_token, set_env_value  # noqa: E402
from voicelens.config import SERVER_DIR, load_settings  # noqa: E402

ENV = SERVER_DIR / ".env"
KEY = "TELEGRAM_DEMO_BOT_TOKEN"


def bot_id_to_find() -> int:
    if len(sys.argv) > 1:
        return int(sys.argv[1])
    load_dotenv(ENV)
    head = (os.getenv(KEY) or "").strip().split(":", 1)[0]
    if head.isdigit():
        return int(head)
    sys.exit("Couldn't tell which bot: run it as  set_bot_token.py <bot id>")


async def main() -> None:
    bot_id = bot_id_to_find()
    settings = load_settings()
    with tempfile.TemporaryDirectory() as tmp:
        session_copy = Path(tmp) / "copy"
        shutil.copy(f"{settings.session_path}.session", f"{session_copy}.session")
        async with TelegramClient(str(session_copy), settings.api_id, settings.api_hash) as client:
            token = None
            async for message in client.iter_messages("BotFather", limit=10):
                token = extract_token(message.raw_text, bot_id)
                if token:
                    break
    if not token:
        sys.exit("No token for that bot in your last 10 @BotFather messages. Send /token to @BotFather and run this again.")
    token = clean_token(token)
    ENV.write_text(set_env_value(ENV.read_text(encoding="utf-8"), KEY, token), encoding="utf-8")
    print(f"Saved the new token for bot {bot_id} to server/.env (not shown).")
    print("Now restart the server and the dashboard so they pick it up.")


if __name__ == "__main__":
    asyncio.run(main())
