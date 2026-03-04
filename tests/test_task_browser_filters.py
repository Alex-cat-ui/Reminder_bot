"""Tests for task browser filter boundaries and list behavior."""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio

import db as database
from handlers.task_browser import _bounds_for_filter


@pytest_asyncio.fixture
async def db_path():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    await database.init_db(path)
    yield path
    os.unlink(path)


def test_today_filter_bounds():
    tz = ZoneInfo("Europe/Moscow")
    now = datetime(2026, 3, 4, 15, 20, tzinfo=tz)
    start, end = _bounds_for_filter("today", now)
    assert start.endswith("00:00:00+03:00")
    assert end.endswith("23:59:59+03:00")


def test_tomorrow_filter_bounds():
    tz = ZoneInfo("Europe/Moscow")
    now = datetime(2026, 3, 4, 15, 20, tzinfo=tz)
    start, end = _bounds_for_filter("tomorrow", now)
    assert start.startswith("2026-03-05T00:00:00")
    assert end.startswith("2026-03-05T23:59:59")


def test_week_filter_bounds():
    tz = ZoneInfo("Europe/Moscow")
    now = datetime(2026, 3, 4, 15, 20, tzinfo=tz)  # Wednesday
    start, end = _bounds_for_filter("week", now)
    assert start.startswith("2026-03-04T15:20:00")
    assert end.startswith("2026-03-11T15:20:00")


@pytest.mark.asyncio
async def test_all_filter_returns_all_active(db_path):
    await database.upsert_user(111, "Europe/Moscow", path=db_path)

    for i in range(3):
        await database.create_event(
            user_id=111,
            event_dt=(datetime(2026, 3, 10, 10, 0, tzinfo=ZoneInfo("Europe/Moscow")) + timedelta(days=i)).isoformat(),
            activity=f"A{i}",
            notes=None,
            path=db_path,
        )

    deleted = await database.create_event(
        user_id=111,
        event_dt=datetime(2026, 3, 20, 10, 0, tzinfo=ZoneInfo("Europe/Moscow")).isoformat(),
        activity="Deleted",
        notes=None,
        path=db_path,
    )
    await database.update_event_status(deleted, "deleted", path=db_path)

    total = await database.count_events_by_filter(111, "all", "", "", path=db_path)
    items = await database.list_events_by_filter(111, "all", None, None, 10, 0, path=db_path)

    assert total == 3
    assert len(items) == 3
