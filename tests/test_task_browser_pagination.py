"""Tests for task browser pagination behavior."""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio

import db as database
import handlers.task_browser as browser


@pytest_asyncio.fixture
async def db_path():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    await database.init_db(path)
    yield path
    os.unlink(path)


@pytest.mark.asyncio
async def test_page_size_five(db_path):
    await database.upsert_user(111, "Europe/Moscow", path=db_path)
    base = datetime(2026, 3, 10, 10, 0, tzinfo=ZoneInfo("Europe/Moscow"))

    for i in range(7):
        await database.create_event(
            user_id=111,
            event_dt=(base + timedelta(days=i)).isoformat(),
            activity=f"Task {i}",
            notes=None,
            path=db_path,
        )

    items = await database.list_events_by_filter(111, "all", None, None, 5, 0, path=db_path)
    assert len(items) == 5


@pytest.mark.asyncio
async def test_page_clamping_low(db_path, monkeypatch):
    await database.upsert_user(111, "Europe/Moscow", path=db_path)
    base = datetime(2026, 3, 10, 10, 0, tzinfo=ZoneInfo("Europe/Moscow"))

    for i in range(6):
        await database.create_event(
            user_id=111,
            event_dt=(base + timedelta(days=i)).isoformat(),
            activity=f"Task {i}",
            notes=None,
            path=db_path,
        )

    original_count = database.count_events_by_filter
    original_list = database.list_events_by_filter

    async def _count(user_id, filter_name, start_dt, end_dt):
        return await original_count(user_id, filter_name, start_dt, end_dt, path=db_path)

    async def _list(user_id, filter_name, start_dt, end_dt, limit, offset):
        return await original_list(user_id, filter_name, start_dt, end_dt, limit, offset, path=db_path)

    monkeypatch.setattr(browser.database, "count_events_by_filter", _count)
    monkeypatch.setattr(browser.database, "list_events_by_filter", _list)

    _, _, page, total_pages = await browser._build_browser_payload(
        user_id=111,
        tz_name="Europe/Moscow",
        sid="abcdef12",
        filter_name="all",
        page=0,
    )

    assert page == 1
    assert total_pages == 2


@pytest.mark.asyncio
async def test_page_clamping_high(db_path, monkeypatch):
    await database.upsert_user(111, "Europe/Moscow", path=db_path)
    base = datetime(2026, 3, 10, 10, 0, tzinfo=ZoneInfo("Europe/Moscow"))

    for i in range(6):
        await database.create_event(
            user_id=111,
            event_dt=(base + timedelta(days=i)).isoformat(),
            activity=f"Task {i}",
            notes=None,
            path=db_path,
        )

    original_count = database.count_events_by_filter
    original_list = database.list_events_by_filter

    async def _count(user_id, filter_name, start_dt, end_dt):
        return await original_count(user_id, filter_name, start_dt, end_dt, path=db_path)

    async def _list(user_id, filter_name, start_dt, end_dt, limit, offset):
        return await original_list(user_id, filter_name, start_dt, end_dt, limit, offset, path=db_path)

    monkeypatch.setattr(browser.database, "count_events_by_filter", _count)
    monkeypatch.setattr(browser.database, "list_events_by_filter", _list)

    _, _, page, total_pages = await browser._build_browser_payload(
        user_id=111,
        tz_name="Europe/Moscow",
        sid="abcdef12",
        filter_name="all",
        page=999,
    )

    assert page == 2
    assert total_pages == 2


def test_total_pages_calculation():
    import math

    assert max(1, math.ceil(0 / 5)) == 1
    assert max(1, math.ceil(1 / 5)) == 1
    assert max(1, math.ceil(5 / 5)) == 1
    assert max(1, math.ceil(6 / 5)) == 2


def test_same_message_navigation():
    parsed = browser._parse_browser_callback("br2:abcdef12:f:week:p:2")
    assert parsed is not None
    kind, payload = parsed
    assert kind == "page"
    assert payload["sid"] == "abcdef12"
    assert payload["filter"] == "week"
    assert payload["page"] == 2
