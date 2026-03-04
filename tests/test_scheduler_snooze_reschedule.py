"""Phase G tests for snooze reschedule behavior."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

import scheduler


@pytest.mark.asyncio
async def test_schedule_snooze_reschedules_event_timeline(monkeypatch):
    tz = ZoneInfo("Europe/Moscow")
    fixed_now = datetime(2026, 3, 4, 10, 0, tzinfo=tz)
    calls = {"update": None, "cancel": None, "schedule": None, "order": []}

    class _FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):  # noqa: D401
            return fixed_now

    async def _get_event(event_id, path="bot.db"):
        return {"id": event_id, "user_id": 111, "status": "active", "snooze_count": 0}

    async def _inc(event_id, path="bot.db"):
        return 1

    async def _get_user(user_id, path="bot.db"):
        return {"timezone": "Europe/Moscow"}

    async def _update_dt(event_id, event_dt, path="bot.db"):
        calls["order"].append("update")
        calls["update"] = (event_id, event_dt)

    async def _cancel(event_id):
        calls["order"].append("cancel")
        calls["cancel"] = event_id

    async def _schedule(event_id, event_dt, user_id, now=None):
        calls["order"].append("schedule")
        calls["schedule"] = (event_id, event_dt, user_id, now)

    monkeypatch.setattr(scheduler, "datetime", _FixedDateTime)
    monkeypatch.setattr(scheduler.database, "get_event", _get_event)
    monkeypatch.setattr(scheduler.database, "increment_snooze", _inc)
    monkeypatch.setattr(scheduler.database, "get_user", _get_user)
    monkeypatch.setattr(scheduler.database, "update_event_datetime", _update_dt)
    monkeypatch.setattr(scheduler, "cancel_event_jobs", _cancel)
    monkeypatch.setattr(scheduler, "schedule_event_jobs", _schedule)

    new_dt = await scheduler.schedule_snooze(10)

    assert new_dt == fixed_now + timedelta(hours=1)
    assert calls["update"] == (10, new_dt.isoformat())
    assert calls["cancel"] == 10
    assert calls["schedule"] == (10, new_dt, 111, fixed_now)
    assert calls["order"] == ["update", "cancel", "schedule"]


@pytest.mark.asyncio
async def test_repeated_snooze_keeps_single_timeline_path(monkeypatch):
    tz = ZoneInfo("Europe/Moscow")
    now_values = [
        datetime(2026, 3, 4, 10, 0, tzinfo=tz),
        datetime(2026, 3, 4, 11, 30, tzinfo=tz),
    ]
    calls: list[tuple[str, int]] = []
    schedule_dts: list[datetime] = []
    increment_values = [1, 2]

    class _SequenceDateTime(datetime):
        @classmethod
        def now(cls, tz=None):  # noqa: D401
            return now_values.pop(0)

    async def _get_event(event_id, path="bot.db"):
        return {"id": event_id, "user_id": 111, "status": "active", "snooze_count": 0}

    async def _inc(event_id, path="bot.db"):
        return increment_values.pop(0)

    async def _get_user(user_id, path="bot.db"):
        return {"timezone": "Europe/Moscow"}

    async def _update_dt(event_id, event_dt, path="bot.db"):
        return None

    async def _cancel(event_id):
        calls.append(("cancel", event_id))

    async def _schedule(event_id, event_dt, user_id, now=None):
        calls.append(("schedule", event_id))
        schedule_dts.append(event_dt)

    monkeypatch.setattr(scheduler, "datetime", _SequenceDateTime)
    monkeypatch.setattr(scheduler.database, "get_event", _get_event)
    monkeypatch.setattr(scheduler.database, "increment_snooze", _inc)
    monkeypatch.setattr(scheduler.database, "get_user", _get_user)
    monkeypatch.setattr(scheduler.database, "update_event_datetime", _update_dt)
    monkeypatch.setattr(scheduler, "cancel_event_jobs", _cancel)
    monkeypatch.setattr(scheduler, "schedule_event_jobs", _schedule)

    dt1 = await scheduler.schedule_snooze(22)
    dt2 = await scheduler.schedule_snooze(22)

    assert dt1 is not None and dt2 is not None
    assert dt2 > dt1
    assert calls == [
        ("cancel", 22),
        ("schedule", 22),
        ("cancel", 22),
        ("schedule", 22),
    ]
    assert schedule_dts == [dt1, dt2]
