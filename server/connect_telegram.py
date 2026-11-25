"""Connect your Telegram account by scanning a QR code (no codes, no keys).

    server\\.venv\\Scripts\\python server\\connect_telegram.py

A QR code opens on screen. On your phone: Telegram > Settings > Devices >
Link Desktop Device, and scan it. That's it. If your account has a cloud
password (two-step verification), you'll be asked for it here.

This is the same "Log in with QR" that Telegram Desktop uses. The session is
saved in server/ (gitignored); end it any time in Telegram > Settings > Devices.
"""

from __future__ import annotations

import asyncio
import getpass
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import qrcode  # noqa: E402
from qrcode.image.svg import SvgPathImage  # noqa: E402
from telethon import TelegramClient  # noqa: E402
from telethon.errors import SessionPasswordNeededError  # noqa: E402

from voicelens.config import load_settings  # noqa: E402


def show_qr(url: str) -> None:
    qr = qrcode.QRCode(border=2)
    qr.add_data(url)
    qr.print_ascii(invert=True)  # in the terminal
    svg = Path(tempfile.gettempdir()) / "voicelens_telegram_qr.svg"
    qr.make_image(image_factory=SvgPathImage).save(svg)  # pure Python, no imaging library
    if sys.platform == "win32":
        os.startfile(svg)  # opens in the browser: easier to scan than the terminal


async def main() -> None:
    settings = load_settings()
    async with TelegramClient(str(settings.session_path), settings.api_id, settings.api_hash) as client:
        if await client.is_user_authorized():
            me = await client.get_me()
            print(f"Already connected as {me.first_name}.")
            return
        print("Telegram > Settings > Devices > Link Desktop Device, then scan this code:\n")
        while True:
            login = await client.qr_login()
            show_qr(login.url)
            try:
                await login.wait(timeout=60)
                break
            except asyncio.TimeoutError:
                print("\nThe code expired. Here is a fresh one:\n")
            except SessionPasswordNeededError:
                await client.sign_in(password=getpass.getpass("Two-step verification password: "))
                break
        me = await client.get_me()
        print(f"\nConnected as {me.first_name}. You can close the QR picture.")


if __name__ == "__main__":
    asyncio.run(main())
