"""Phase 5 tests: undo delete callbacks."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

import handlers.task_browser as browser


class _FakeUser:
    def __init__(self, user_id: int):
        self.id = user_id


class _FakeMessage:
    def __init__(self):
        self.answered = []
        self.reply_markup_cleared = False

    async def answer(self, text, reply_markup=None):
        self.answered.append((text, reply_markup))

    async def edit_reply_markup(self, reply_markup=None):
        self.reply_markup_cleared = True


class _FakeCallback:
    def __init__(self, data: str, user_id: int):
        self.data = data
        self.from_user = _FakeUser(user_id)
        self.message = _FakeMessage()
        self.answers = []

    async def answer(self, text=None, show_alert=False):
        self.answers.append((text, show_alert))


@pytest.mark.asyncio
async def test_undo_success(monkeypatch):
    cb = _FakeCallback("undo2:abcdef123456", 111)
    undo = {
        "status": "active",
        "user_id": 111,
        "event_id": 77,
        "expires_at": (datetime.utcnow() + timedelta(minutes=10)).isoformat(),
    }
    event = {"id": 77, "status": "deleted", "event_dt": "2026-03-10T10:00:00+03:00"}
    called = {"status": None, "used": None, "schedule": None}

    async def _get_undo(token):
        return undo

    async def _get_event(event_id):
        return event

    async def _update_status(event_id, status):
        called["status"] = (event_id, status)

    async def _mark_used(token, used_at):
        called["used"] = (token, used_at)

    async def _schedule(event_id, event_dt, user_id):
        called["schedule"] = (event_id, event_dt, user_id)

    monkeypatch.setattr(browser.database, "get_undo_action", _get_undo)
    monkeypatch.setattr(browser.database, "get_event", _get_event)
    monkeypatch.setattr(browser.database, "update_event_status", _update_status)
    monkeypatch.setattr(browser.database, "mark_undo_action_used", _mark_used)
    monkeypatch.setattr(browser, "schedule_event_jobs", _schedule)

    await browser.on_undo_callback(cb)

    assert called["status"] == (77, "active")
    assert called["used"] is not None
    assert called["schedule"] is not None
    assert cb.answers[-1] == ("Удаление отменено.", False)
    assert cb.message.reply_markup_cleared is True


@pytest.mark.asyncio
async def test_undo_expired(monkeypatch):
    cb = _FakeCallback("undo2:abcdef123456", 111)
    undo = {
        "status": "active",
        "user_id": 111,
        "event_id": 77,
        "expires_at": (datetime.utcnow() - timedelta(minutes=1)).isoformat(),
    }
    called = {"expired": False, "status": False}

    async def _get_undo(token):
        return undo

    async def _mark_expired(token):
        called["expired"] = True

    async def _update_status(event_id, status):
        called["status"] = True

    monkeypatch.setattr(browser.database, "get_undo_action", _get_undo)
    monkeypatch.setattr(browser.database, "mark_undo_action_expired", _mark_expired)
    monkeypatch.setattr(browser.database, "update_event_status", _update_status)

    await browser.on_undo_callback(cb)

    assert called["expired"] is True
    assert called["status"] is False
    assert cb.answers[-1] == ("Срок отмены удаления истек.", True)


@pytest.mark.asyncio
async def test_undo_rejects_wrong_user(monkeypatch):
    cb = _FakeCallback("undo2:abcdef123456", 222)
    undo = {
        "status": "active",
        "user_id": 111,
        "event_id": 77,
        "expires_at": (datetime.utcnow() + timedelta(minutes=10)).isoformat(),
    }
    called = {"status": False}

    async def _get_undo(token):
        return undo

    async def _update_status(event_id, status):
        called["status"] = True

    monkeypatch.setattr(browser.database, "get_undo_action", _get_undo)
    monkeypatch.setattr(browser.database, "update_event_status", _update_status)

    await browser.on_undo_callback(cb)

    assert called["status"] is False
    assert cb.answers[-1] == ("Задача не найдена или недоступна.", True)
