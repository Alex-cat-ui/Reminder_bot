"""Tests for timezone flow cancel behavior."""

import pytest

from handlers import timezone as tz_mod


class _FakeUser:
    def __init__(self, user_id: int):
        self.id = user_id


class _FakeMessage:
    def __init__(self, text: str, user_id: int):
        self.text = text
        self.from_user = _FakeUser(user_id)
        self.sent = []

    async def answer(self, text, reply_markup=None):
        self.sent.append((text, reply_markup))


class _FakeState:
    def __init__(self):
        self.cleared = False

    async def clear(self):
        self.cleared = True


@pytest.mark.asyncio
async def test_timezone_cancel_returns_to_main_menu(monkeypatch):
    msg = _FakeMessage("Отмена", 111)
    state = _FakeState()

    called = {"upsert": False}

    async def _upsert(*args, **kwargs):
        called["upsert"] = True

    monkeypatch.setattr(tz_mod.database, "upsert_user", _upsert)

    await tz_mod.process_tz(msg, state)

    assert state.cleared is True
    assert called["upsert"] is False
    assert msg.sent
    assert msg.sent[-1][0] == "Выбор часового пояса отменен."


@pytest.mark.asyncio
async def test_timezone_legacy_cancel_with_marker_is_supported(monkeypatch):
    msg = _FakeMessage("🟥 Отмена", 111)
    state = _FakeState()

    called = {"upsert": False}

    async def _upsert(*args, **kwargs):
        called["upsert"] = True

    monkeypatch.setattr(tz_mod.database, "upsert_user", _upsert)

    await tz_mod.process_tz(msg, state)

    assert state.cleared is True
    assert called["upsert"] is False
    assert msg.sent
    assert msg.sent[-1][0] == "Выбор часового пояса отменен."
