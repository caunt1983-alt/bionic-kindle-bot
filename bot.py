"""Telegram-бот bionic-конвертер с отправкой на Kindle через Gmail SMTP.

Флоу:
1. Ты форвардишь .epub боту в личку (из группы «Бубубу» → «Переслать»).
2. Бот молча конвертирует через process_epub из bionicize.py.
3. Бот шлёт результат на @kindle.com через Gmail SMTP (порт 465, SSL).
4. Через 1–3 минуты книга на Kindle-приложении.

Файлы >20 МБ отбрасывает (лимит Bot API).
Работает только с BotHost — с локального ПК Gmail SMTP закрыт ISP/VPN.
"""
from __future__ import annotations

import asyncio
import logging
import os
import smtplib
import ssl
import sys
import tempfile
from email.message import EmailMessage
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message
from dotenv import load_dotenv

from bionicize import process_epub

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN") or os.getenv("API_TOKEN")
OWNER_USER_ID = int(os.getenv("OWNER_USER_ID", "0")) or None
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "").replace(" ", "")
KINDLE_EMAIL = os.getenv("KINDLE_EMAIL")

MAX_SIZE = 20 * 1024 * 1024

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

bot = Bot(BOT_TOKEN)
dp = Dispatcher()


def send_to_kindle(path: Path, filename: str) -> None:
    msg = EmailMessage()
    msg["From"] = GMAIL_USER
    msg["To"] = KINDLE_EMAIL
    msg["Subject"] = filename
    msg.set_content("Sent by bionic-kindle-bot")
    with path.open("rb") as f:
        msg.add_attachment(
            f.read(),
            maintype="application",
            subtype="epub+zip",
            filename=filename,
        )
    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx, timeout=60) as s:
        s.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        s.send_message(msg)


@dp.message(Command("id"))
async def cmd_id(message: Message) -> None:
    await message.reply(
        f"chat_id: {message.chat.id}\n"
        f"user_id: {message.from_user.id if message.from_user else '?'}\n"
        f"type: {message.chat.type}"
    )


@dp.message(F.document)
async def on_document(message: Message) -> None:
    if message.chat.type != "private":
        return
    if OWNER_USER_ID and message.from_user and message.from_user.id != OWNER_USER_ID:
        return

    doc = message.document
    name = (doc.file_name or "").lower()
    if not name.endswith(".epub"):
        await message.reply("Только .epub. Всё остальное игнорирую.")
        return

    if doc.file_size and doc.file_size > MAX_SIZE:
        mb = doc.file_size / (1024 * 1024)
        await message.reply(
            f"⚠️ {mb:.1f} МБ, лимит 20 — обработай локально через ZAPUSTIT.bat"
        )
        return

    status = await message.reply("⏳ Обрабатываю…")

    with tempfile.TemporaryDirectory() as td:
        stem = Path(doc.file_name).stem
        out_stem = stem if stem.endswith("_bionic") else f"{stem}_bionic"
        src = Path(td) / doc.file_name
        dst = Path(td) / f"{out_stem}.epub"
        try:
            await bot.download(doc, destination=src)
        except Exception as e:
            log.exception("download failed")
            await status.edit_text(f"❌ Не смог скачать: {e}")
            return

        try:
            docs, words = await asyncio.to_thread(process_epub, src, dst)
        except Exception as e:
            log.exception("process_epub failed")
            await status.edit_text(f"❌ Не смог обработать EPUB: {e}")
            return

        if words == 0:
            await status.edit_text("❌ В EPUB не нашлось текста для обработки")
            return

        await status.edit_text(f"📧 Отправляю на Kindle ({docs} док., {words} слов)…")

        try:
            await asyncio.to_thread(send_to_kindle, dst, dst.name)
        except Exception as e:
            log.exception("smtp failed")
            await status.edit_text(f"❌ SMTP: {e}")
            return

    await status.edit_text(f"✓ Отправлено на Kindle: {out_stem}.epub")


async def main() -> None:
    missing = [n for n, v in [
        ("BOT_TOKEN/API_TOKEN", BOT_TOKEN),
        ("GMAIL_USER", GMAIL_USER),
        ("GMAIL_APP_PASSWORD", GMAIL_APP_PASSWORD),
        ("KINDLE_EMAIL", KINDLE_EMAIL),
    ] if not v]
    if missing:
        log.error("Нет обязательных env: %s", ", ".join(missing))
        sys.exit(1)
    log.info("OWNER_USER_ID=%s GMAIL_USER=%s KINDLE_EMAIL=%s",
             OWNER_USER_ID, GMAIL_USER, KINDLE_EMAIL)
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())
