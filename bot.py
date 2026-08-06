"""Telegram-бот bionic-конвертер.

Флоу:
1. Ты форвардишь .epub боту в личку (из группы «Бубубу» → «Переслать»).
2. Бот молча конвертирует через process_epub из bionicize.py.
3. Бот присылает bionic-версию обратно в личку.

Файлы >20 МБ отбрасывает (лимит Bot API).
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import tempfile
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import FSInputFile, Message
from dotenv import load_dotenv

from bionicize import process_epub

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_USER_ID = int(os.getenv("OWNER_USER_ID", "0")) or None

MAX_SIZE = 20 * 1024 * 1024

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

bot = Bot(BOT_TOKEN)
dp = Dispatcher()


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

        try:
            await bot.send_document(
                chat_id=message.chat.id,
                document=FSInputFile(dst, filename=dst.name),
                caption=f"bionic: {docs} док., {words} слов",
                reply_to_message_id=message.message_id,
            )
        except Exception as e:
            log.exception("send_document failed")
            await status.edit_text(f"❌ Не смог отправить: {e}")
            return

    try:
        await status.delete()
    except Exception:
        pass


async def main() -> None:
    if not BOT_TOKEN:
        log.error("BOT_TOKEN не задан")
        sys.exit(1)
    log.info("OWNER_USER_ID=%s", OWNER_USER_ID)
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())
