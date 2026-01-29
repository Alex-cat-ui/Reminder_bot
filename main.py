"""Entry point for the Telegram reminder bot."""

from __future__ import annotations

import asyncio
import logging
import sys
import os

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import TELEGRAM_BOT_TOKEN, DB_PATH, LOG_FILE

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties

import db as database
from scheduler import scheduler as apscheduler, set_bot, restore_jobs_on_startup
from handlers import router as main_router


def setup_logging() -> None:
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    logging.basicConfig(
        level=logging.INFO,
        format=fmt,
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
        ],
    )


async def main() -> None:
    setup_logging()
    logger = logging.getLogger(__name__)
    logger.info("Starting bot...")

    await database.init_db(DB_PATH)

    bot = Bot(token=TELEGRAM_BOT_TOKEN, default=DefaultBotProperties(parse_mode=None))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(main_router)

    database.DB_PATH = DB_PATH
    set_bot(bot, DB_PATH)

    apscheduler.start()
    await restore_jobs_on_startup()

    logger.info("Bot is running.")
    try:
        await dp.start_polling(bot)
    finally:
        apscheduler.shutdown()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
