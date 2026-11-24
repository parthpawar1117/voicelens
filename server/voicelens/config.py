"""Settings loaded from server/.env (never committed). See server/env.example."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

SERVER_DIR = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    api_id: int
    api_hash: str
    session_path: Path
    port: int
    demo_bot_token: str | None = None  # optional demo-friend bot


class MissingSettingError(RuntimeError):
    pass


def load_settings() -> Settings:
    load_dotenv(SERVER_DIR / ".env")
    api_id = os.getenv("TELEGRAM_API_ID", "")
    api_hash = os.getenv("TELEGRAM_API_HASH", "")
    if not api_id.isdigit() or not api_hash or api_hash.startswith("replace_"):
        raise MissingSettingError(
            "Set TELEGRAM_API_ID and TELEGRAM_API_HASH in server/.env "
            "(copy server/env.example). Get them at https://my.telegram.org."
        )
    session_name = os.getenv("TELEGRAM_SESSION_NAME", "voicelens")
    return Settings(
        api_id=int(api_id),
        api_hash=api_hash,
        session_path=SERVER_DIR / session_name,
        port=int(os.getenv("SERVER_PORT", "8787")),
        demo_bot_token=(os.getenv("TELEGRAM_DEMO_BOT_TOKEN") or "").strip().strip("'\"").strip() or None,
    )
