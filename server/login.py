"""One-time Telegram login. Run it yourself in a terminal:

    server/.venv/Scripts/python server/login.py

Telethon asks for your phone number and the code Telegram sends you, then saves
a session file (server/<TELEGRAM_SESSION_NAME>.session, gitignored). Treat that
file like a password: anyone with it can use your account. Delete it to log out
of this device, or end the session in Telegram > Settings > Devices.
"""

from telethon.sync import TelegramClient

from voicelens.config import load_settings


def main() -> None:
    settings = load_settings()
    with TelegramClient(str(settings.session_path), settings.api_id, settings.api_hash) as client:
        me = client.get_me()
        print(f"Logged in as {me.first_name} (session saved).")


if __name__ == "__main__":
    main()
