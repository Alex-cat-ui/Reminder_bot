"""Security tests for callback ownership checks."""

import pytest

from handlers import callbacks as cb_mod


class _FakeUser:
    def __init__(self, user_id: int):
        self.id = user_id


class _FakeMessage:
    def __init__(self):
        self.answered = []
        self.reply_markup_cleared = False

    async def edit_reply_markup(self, reply_markup=None):
        self.reply_markup_cleared = True

    async def answer(self, text, reply_markup=None):
        self.answered.append((text, reply_markup))


class _FakeCallback:
    def __init__(self, data: str, user_id: int):
        self.data = data
        self.from_user = _FakeUser(user_id)
        self.message = _FakeMessage()
        self.answers = []

    async def answer(self, text=None, show_alert=False):
        self.answers.append((text, show_alert))


@pytest.mark.asyncio
async def test_snooze_rejects_wrong_user(monkeypatch):
    cb = _FakeCallback("snooze:101", 555)

    async def _no_event(event_id, user_id):
        return None

    called = {"schedule": False}

    async def _schedule(event_id):
        called["schedule"] = True
        return None

    monkeypatch.setattr(cb_mod.database, "get_active_event_for_user", _no_event)
    monkeypatch.setattr(cb_mod, "schedule_snooze", _schedule)

    await cb_mod.on_snooze(cb)

    assert called["schedule"] is False
    assert cb.answers[-1] == ("Задача не найдена или недоступна.", True)


@pytest.mark.asyncio
async def test_done_rejects_wrong_user(monkeypatch):
    cb = _FakeCallback("done:101", 555)

    async def _no_event(event_id, user_id):
        return None

    called = {"status": False, "cancel": False}

    async def _status(event_id, status):
        called["status"] = True

    async def _cancel(event_id):
        called["cancel"] = True

    monkeypatch.setattr(cb_mod.database, "get_active_event_for_user", _no_event)
    monkeypatch.setattr(cb_mod.database, "update_event_status", _status)
    monkeypatch.setattr(cb_mod, "cancel_event_jobs", _cancel)

    await cb_mod.on_done(cb)

    assert called == {"status": False, "cancel": False}
    assert cb.answers[-1] == ("Задача не найдена или недоступна.", True)


@pytest.mark.asyncio
async def test_delete_rejects_wrong_user(monkeypatch):
    cb = _FakeCallback("delete:101", 555)

    async def _no_event(event_id, user_id):
        return None

    called = {"status": False, "cancel": False}

    async def _status(event_id, status):
        called["status"] = True

    async def _cancel(event_id):
        called["cancel"] = True

    monkeypatch.setattr(cb_mod.database, "get_active_event_for_user", _no_event)
    monkeypatch.setattr(cb_mod.database, "update_event_status", _status)
    monkeypatch.setattr(cb_mod, "cancel_event_jobs", _cancel)

    await cb_mod.on_delete(cb)

    assert called == {"status": False, "cancel": False}
    assert cb.answers[-1] == ("Задача не найдена или недоступна.", True)
