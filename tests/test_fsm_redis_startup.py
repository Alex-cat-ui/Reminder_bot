"""Phase 6 tests: Redis FSM storage and startup fail-fast."""

from __future__ import annotations

import pytest

import main


@pytest.mark.asyncio
async def test_create_fsm_storage_uses_redis_builder(monkeypatch):
    fake_client = object()
    fake_storage = object()
    called = {"client": None, "builder": None}

    async def _create_client(redis_dsn):
        called["client"] = redis_dsn
        return fake_client

    def _build_storage(redis_client, ttl_seconds):
        called["builder"] = (redis_client, ttl_seconds)
        return fake_storage

    monkeypatch.setattr(main, "_create_redis_client", _create_client)
    monkeypatch.setattr(main, "_build_redis_storage", _build_storage)

    storage = await main.create_fsm_storage("redis://localhost:6379/0", 120)

    assert storage is fake_storage
    assert called["client"] == "redis://localhost:6379/0"
    assert called["builder"] == (fake_client, 120)


@pytest.mark.asyncio
async def test_main_uses_injected_redis_storage(monkeypatch):
    called = {"storage": None, "polling": False, "create_storage": False}

    class _FakeBotSession:
        async def close(self):
            return None

    class _FakeBot:
        def __init__(self, token, default):
            self.token = token
            self.default = default
            self.session = _FakeBotSession()

    class _FakeStorage:
        async def close(self):
            return None

    class _FakeDispatcher:
        def __init__(self, storage):
            called["storage"] = storage
            self.storage = storage

        def include_router(self, router):
            return None

        async def start_polling(self, bot):
            called["polling"] = True

    fake_storage = _FakeStorage()

    async def _create_storage(redis_dsn, ttl):
        called["create_storage"] = True
        return fake_storage

    async def _init_db(path):
        return None

    async def _restore():
        return None

    def _set_bot(bot, path):
        return None

    class _FakeScheduler:
        def start(self):
            return None

        def shutdown(self):
            return None

    monkeypatch.setattr(main, "TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setattr(main, "REDIS_DSN", "redis://localhost:6379/0")
    monkeypatch.setattr(main, "FSM_TTL_SECONDS", 120)
    monkeypatch.setattr(main, "Bot", _FakeBot)
    monkeypatch.setattr(main, "Dispatcher", _FakeDispatcher)
    monkeypatch.setattr(main, "create_fsm_storage", _create_storage)
    monkeypatch.setattr(main.database, "init_db", _init_db)
    monkeypatch.setattr(main, "restore_jobs_on_startup", _restore)
    monkeypatch.setattr(main, "set_bot", _set_bot)
    monkeypatch.setattr(main, "apscheduler", _FakeScheduler())

    await main.main()

    assert called["create_storage"] is True
    assert called["storage"] is fake_storage
    assert called["polling"] is True


@pytest.mark.asyncio
async def test_main_fails_fast_when_redis_unavailable(monkeypatch):
    async def _init_db(path):
        return None

    async def _create_storage(redis_dsn, ttl):
        raise RuntimeError("Redis is unavailable.")

    monkeypatch.setattr(main, "TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setattr(main, "REDIS_DSN", "redis://localhost:6379/0")
    monkeypatch.setattr(main, "FSM_TTL_SECONDS", 120)
    monkeypatch.setattr(main.database, "init_db", _init_db)
    monkeypatch.setattr(main, "create_fsm_storage", _create_storage)

    with pytest.raises(RuntimeError, match="Redis is unavailable."):
        await main.main()
