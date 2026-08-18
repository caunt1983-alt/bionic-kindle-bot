"""Telegram-бот bionic-конвертер с отправкой на Kindle через Resend HTTPS API.

Флоу:
1. Ты форвардишь .epub боту в личку (из группы «Бубубу» → «Переслать»).
2. Бот молча конвертирует через process_epub из bionicize.py.
3. Бот шлёт результат на твой @kindle.com через HTTP-API Resend.
4. Через минуту книга на Kindle-приложении.

Файлы >20 МБ отбрасывает (лимит Bot API).
"""
from __future__ import annotations

import asyncio
import base64
import logging
import os
import sys
import tempfile
from pathlib import Path

import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message
from dotenv import load_dotenv

from bionicize import process_epub

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN") or os.getenv("API_TOKEN")
OWNER_USER_ID = int(os.getenv("OWNER_USER_ID", "0")) or None
RESEND_API_KEY = os.getenv("RESEND_API_KEY")
RESEND_FROM = os.getenv("RESEND_FROM", "onboarding@resend.dev")
KINDLE_EMAIL = os.getenv("KINDLE_EMAIL")

MAX_SIZE = 20 * 1024 * 1024

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

bot = Bot(BOT_TOKEN)
dp = Dispatcher()


async def send_to_kindle(path: Path, filename: str) -> None:
    payload = {
        "from": RESEND_FROM,
        "to": KINDLE_EMAIL,
        "subject": filename,
        "text": "Sent by bionic-kindle-bot",
        "attachments": [{
            "filename": filename,
            "content": base64.b64encode(path.read_bytes()).decode(),
        }],
    }
    headers = {
        "Authorization": f"Bearer {RESEND_API_KEY}",
        "Content-Type": "application/json",
    }
    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession(timeout=timeout) as s:
        async with s.post("https://api.resend.com/emails",
                          json=payload, headers=headers) as r:
            body = await r.text()
            if r.status >= 300:
                raise RuntimeError(f"Resend {r.status}: {body[:300]}")


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
            await send_to_kindle(dst, dst.name)
        except Exception as e:
            log.exception("send_to_kindle failed")
            await status.edit_text(f"❌ Resend: {e}")
            return

    await status.edit_text(f"✓ Отправлено на Kindle: {out_stem}.epub")


async def main() -> None:
    missing = [n for n, v in [
        ("BOT_TOKEN", BOT_TOKEN),
        ("RESEND_API_KEY", RESEND_API_KEY),
        ("KINDLE_EMAIL", KINDLE_EMAIL),
    ] if not v]
    if missing:
        log.error("Нет обязательных env: %s", ", ".join(missing))
        sys.exit(1)
    log.info("OWNER_USER_ID=%s FROM=%s TO=%s", OWNER_USER_ID, RESEND_FROM, KINDLE_EMAIL)
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())
