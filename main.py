"""Entry point for the Telegram reminder bot."""

from __future__ import annotations

import asyncio
import logging
import sys
import os
from typing import Any

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import TELEGRAM_BOT_TOKEN, DB_PATH, LOG_FILE, REDIS_DSN, FSM_TTL_SECONDS

from aiogram import Bot, Dispatcher
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


def _validate_startup_config() -> None:
    missing = []
    if not TELEGRAM_BOT_TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not REDIS_DSN:
        missing.append("REDIS_DSN")
    if missing:
        joined = ", ".join(missing)
        raise RuntimeError(f"Missing required settings: {joined}")
    if FSM_TTL_SECONDS <= 0:
        raise RuntimeError("FSM_TTL_SECONDS must be > 0")


async def _safe_close_redis(redis_client: Any) -> None:
    close_async = getattr(redis_client, "aclose", None)
    if close_async is not None:
        await close_async()
        return
    close_sync = getattr(redis_client, "close", None)
    if close_sync is not None:
        result = close_sync()
        if hasattr(result, "__await__"):
            await result


async def _create_redis_client(redis_dsn: str) -> Any:
    if not redis_dsn:
        raise RuntimeError("REDIS_DSN is not set.")
    try:
        from redis.asyncio import Redis  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("Redis dependency is missing.") from exc

    client = Redis.from_url(redis_dsn, encoding="utf-8", decode_responses=True)
    try:
        await client.ping()
    except Exception as exc:
        await _safe_close_redis(client)
        raise RuntimeError("Redis is unavailable.") from exc
    return client


def _build_redis_storage(redis_client: Any, ttl_seconds: int):
    try:
        from aiogram.fsm.storage.redis import RedisStorage
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("Redis storage backend is unavailable.") from exc

    return RedisStorage(
        redis=redis_client,
        state_ttl=ttl_seconds,
        data_ttl=ttl_seconds,
    )


async def create_fsm_storage(redis_dsn: str, ttl_seconds: int):
    redis_client = await _create_redis_client(redis_dsn)
    return _build_redis_storage(redis_client, ttl_seconds)


async def main() -> None:
    setup_logging()
    logger = logging.getLogger(__name__)
    logger.info("Starting bot...")

    _validate_startup_config()
    await database.init_db(DB_PATH)
    storage = await create_fsm_storage(REDIS_DSN, FSM_TTL_SECONDS)

    bot = Bot(token=TELEGRAM_BOT_TOKEN, default=DefaultBotProperties(parse_mode=None))
    dp = Dispatcher(storage=storage)
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
        await dp.storage.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
