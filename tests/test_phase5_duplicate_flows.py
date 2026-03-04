"""Phase 5 tests: duplicate guards for create/clone/edit datetime."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

import handlers.event_edit as event_edit
import handlers.task_browser as browser
import handlers.wizard as wizard


class _FakeState:
    def __init__(self, data: dict | None = None):
        self.data = dict(data or {})
        self.current_state = None
        self.cleared = False

    async def get_data(self):
        return dict(self.data)

    async def update_data(self, **kwargs):
        self.data.update(kwargs)

    async def set_state(self, state):
        self.current_state = state

    async def clear(self):
        self.data.clear()
        self.current_state = None
        self.cleared = True


@pytest.mark.asyncio
async def test_create_duplicate_guard_blocks_save(monkeypatch):
    state = _FakeState(
        {
            "event_dt": "2026-03-10T10:00:00+03:00",
            "activity": "Workout",
            "notes": "Leg day",
        }
    )
    called = {"create": False}

    async def _has_duplicate(**kwargs):
        return True

    async def _create_event(**kwargs):
        called["create"] = True
        return 1

    monkeypatch.setattr(wizard, "has_duplicate_event", _has_duplicate)
    monkeypatch.setattr(wizard.database, "create_event", _create_event)

    ok, error = await wizard._finalize_create(state, user_id=111, duplicate_override=False)

    assert ok is False
    assert error == "DUPLICATE"
    assert called["create"] is False
    assert state.data.get("create_dup_sid")


@pytest.mark.asyncio
async def test_create_duplicate_override_saves(monkeypatch):
    state = _FakeState(
        {
            "event_dt": "2026-03-10T10:00:00+03:00",
            "activity": "Workout",
            "notes": "Leg day",
            "create_dup_sid": "abcdef12",
        }
    )
    called = {"create": None, "schedule": None}

    async def _create_event(**kwargs):
        called["create"] = kwargs
        return 55

    async def _schedule(event_id, dt, user_id):
        called["schedule"] = (event_id, dt, user_id)

    monkeypatch.setattr(wizard.database, "create_event", _create_event)
    monkeypatch.setattr(wizard, "schedule_event_jobs", _schedule)

    ok, error = await wizard._finalize_create(state, user_id=111, duplicate_override=True)

    assert ok is True
    assert error is None
    assert called["create"] is not None
    assert called["schedule"] is not None
    assert state.cleared is True


@pytest.mark.asyncio
async def test_clone_duplicate_guard_blocks_save(monkeypatch):
    state = _FakeState(
        {
            "clone_event_dt_iso": "2026-03-10T10:00:00+03:00",
            "clone_activity": "Workout",
            "clone_notes": "Leg day",
        }
    )
    called = {"create": False}

    async def _has_duplicate(**kwargs):
        return True

    async def _create_event(**kwargs):
        called["create"] = True
        return 1

    monkeypatch.setattr(browser, "has_duplicate_event", _has_duplicate)
    monkeypatch.setattr(browser.database, "create_event", _create_event)

    ok, error = await browser._finalize_clone(state, user_id=111)

    assert ok is False
    assert error == "DUPLICATE"
    assert called["create"] is False
    assert state.data.get("clone_dup_sid")


@pytest.mark.asyncio
async def test_clone_success_schedules_jobs(monkeypatch):
    state = _FakeState(
        {
            "clone_event_dt_iso": "2026-03-10T10:00:00+03:00",
            "clone_activity": "Workout",
            "clone_notes": "Leg day",
        }
    )
    called = {"create": None, "schedule": None}

    async def _has_duplicate(**kwargs):
        return False

    async def _create_event(**kwargs):
        called["create"] = kwargs
        return 99

    async def _schedule(event_id, dt, user_id):
        called["schedule"] = (event_id, dt, user_id)

    monkeypatch.setattr(browser, "has_duplicate_event", _has_duplicate)
    monkeypatch.setattr(browser.database, "create_event", _create_event)
    monkeypatch.setattr(browser, "schedule_event_jobs", _schedule)

    ok, error = await browser._finalize_clone(state, user_id=111)

    assert ok is True
    assert error is None
    assert called["create"] is not None
    assert called["schedule"] is not None
    assert state.cleared is True


@pytest.mark.asyncio
async def test_edit_datetime_duplicate_guard_blocks_save(monkeypatch):
    tz = ZoneInfo("Europe/Moscow")
    tomorrow = (datetime.now(tz) + timedelta(days=1)).date().isoformat()
    state = _FakeState(
        {
            "edit_event_id": 7,
            "edit_timezone": "Europe/Moscow",
            "edit_selected_date_iso": tomorrow,
        }
    )
    called = {"update": False}

    async def _get_event(event_id, user_id):
        return {"id": event_id, "activity": "Workout"}

    async def _has_duplicate(**kwargs):
        return True

    async def _update_dt(event_id, event_dt):
        called["update"] = True

    monkeypatch.setattr(event_edit.database, "get_active_event_for_user", _get_event)
    monkeypatch.setattr(event_edit, "has_duplicate_event", _has_duplicate)
    monkeypatch.setattr(event_edit.database, "update_event_datetime", _update_dt)

    ok, error = await event_edit._apply_edit_datetime(state, user_id=111, hour=10, minute=0)

    assert ok is False
    assert error == "DUPLICATE"
    assert called["update"] is False
    assert state.current_state == event_edit.EditEventStates.edit_confirm_duplicate
    assert state.data.get("edit_dup_sid")


@pytest.mark.asyncio
async def test_edit_datetime_duplicate_override_saves(monkeypatch):
    tz = ZoneInfo("Europe/Moscow")
    tomorrow = (datetime.now(tz) + timedelta(days=1)).date().isoformat()
    state = _FakeState(
        {
            "edit_event_id": 7,
            "edit_timezone": "Europe/Moscow",
            "edit_selected_date_iso": tomorrow,
        }
    )
    called = {"update": None, "cancel": None, "schedule": None}

    async def _get_event(event_id, user_id):
        return {"id": event_id, "activity": "Workout"}

    async def _update_dt(event_id, event_dt):
        called["update"] = (event_id, event_dt)

    async def _cancel_jobs(event_id):
        called["cancel"] = event_id

    async def _schedule(event_id, event_dt, user_id):
        called["schedule"] = (event_id, event_dt, user_id)

    monkeypatch.setattr(event_edit.database, "get_active_event_for_user", _get_event)
    monkeypatch.setattr(event_edit.database, "update_event_datetime", _update_dt)
    monkeypatch.setattr(event_edit, "cancel_event_jobs", _cancel_jobs)
    monkeypatch.setattr(event_edit, "schedule_event_jobs", _schedule)

    ok, error = await event_edit._apply_edit_datetime(
        state,
        user_id=111,
        hour=10,
        minute=0,
        duplicate_override=True,
    )

    assert ok is True
    assert error is None
    assert called["update"] is not None
    assert called["cancel"] == 7
    assert called["schedule"] is not None
    assert state.cleared is True
