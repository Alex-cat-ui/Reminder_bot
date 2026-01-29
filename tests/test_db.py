"""Integration tests for SQLite database layer."""

import os
import pytest
import pytest_asyncio
import tempfile
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import db as database


@pytest_asyncio.fixture
async def db_path():
    """Create a temporary database for each test."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    await database.init_db(path)
    yield path
    os.unlink(path)


@pytest.mark.asyncio
class TestUserCRUD:
    async def test_create_and_get_user(self, db_path):
        await database.upsert_user(111, "Europe/Moscow", path=db_path)
        user = await database.get_user(111, path=db_path)
        assert user is not None
        assert user["user_id"] == 111
        assert user["timezone"] == "Europe/Moscow"

    async def test_update_timezone(self, db_path):
        await database.upsert_user(111, "Europe/Moscow", path=db_path)
        await database.upsert_user(111, "Asia/Tokyo", path=db_path)
        user = await database.get_user(111, path=db_path)
        assert user["timezone"] == "Asia/Tokyo"

    async def test_get_nonexistent_user(self, db_path):
        user = await database.get_user(999, path=db_path)
        assert user is None


@pytest.mark.asyncio
class TestEventCRUD:
    async def test_create_event(self, db_path):
        await database.upsert_user(111, "Europe/Moscow", path=db_path)
        eid = await database.create_event(
            user_id=111,
            event_dt="2025-12-25T18:00:00+03:00",
            activity="Meeting",
            notes="Some notes",
            path=db_path,
        )
        assert eid is not None
        event = await database.get_event(eid, path=db_path)
        assert event["activity"] == "Meeting"
        assert event["status"] == "active"
        assert event["snooze_count"] == 0

    async def test_update_status(self, db_path):
        await database.upsert_user(111, "Europe/Moscow", path=db_path)
        eid = await database.create_event(
            user_id=111,
            event_dt="2025-12-25T18:00:00+03:00",
            activity="Test",
            notes=None,
            path=db_path,
        )
        await database.update_event_status(eid, "done", path=db_path)
        event = await database.get_event(eid, path=db_path)
        assert event["status"] == "done"

    async def test_increment_snooze(self, db_path):
        await database.upsert_user(111, "Europe/Moscow", path=db_path)
        eid = await database.create_event(
            user_id=111,
            event_dt="2025-12-25T18:00:00+03:00",
            activity="Test",
            notes=None,
            path=db_path,
        )
        count = await database.increment_snooze(eid, path=db_path)
        assert count == 1
        count = await database.increment_snooze(eid, path=db_path)
        assert count == 2

    async def test_snooze_limit_25(self, db_path):
        """Incrementing snooze 25 times should work; 26th increment goes beyond limit."""
        await database.upsert_user(111, "Europe/Moscow", path=db_path)
        eid = await database.create_event(
            user_id=111,
            event_dt="2025-12-25T18:00:00+03:00",
            activity="Test",
            notes=None,
            path=db_path,
        )
        for i in range(25):
            count = await database.increment_snooze(eid, path=db_path)
        assert count == 25
        # 26th
        count = await database.increment_snooze(eid, path=db_path)
        assert count == 26  # DB allows it; scheduler checks the limit


@pytest.mark.asyncio
class TestWeekEvents:
    async def test_get_week_events(self, db_path):
        await database.upsert_user(111, "Europe/Moscow", path=db_path)
        # Create event within range
        await database.create_event(
            user_id=111,
            event_dt="2025-06-11T18:00:00+03:00",
            activity="In range",
            notes=None,
            path=db_path,
        )
        # Create event outside range
        await database.create_event(
            user_id=111,
            event_dt="2025-07-01T18:00:00+03:00",
            activity="Out of range",
            notes=None,
            path=db_path,
        )
        events = await database.get_week_events(
            111,
            "2025-06-09T00:00:00+03:00",
            "2025-06-15T23:59:59+03:00",
            path=db_path,
        )
        assert len(events) == 1
        assert events[0]["activity"] == "In range"

    async def test_deleted_events_excluded(self, db_path):
        await database.upsert_user(111, "Europe/Moscow", path=db_path)
        eid = await database.create_event(
            user_id=111,
            event_dt="2025-06-11T18:00:00+03:00",
            activity="Deleted",
            notes=None,
            path=db_path,
        )
        await database.update_event_status(eid, "deleted", path=db_path)
        events = await database.get_week_events(
            111,
            "2025-06-09T00:00:00+03:00",
            "2025-06-15T23:59:59+03:00",
            path=db_path,
        )
        assert len(events) == 0


@pytest.mark.asyncio
class TestJobsCRUD:
    async def test_create_and_get_jobs(self, db_path):
        await database.upsert_user(111, "Europe/Moscow", path=db_path)
        eid = await database.create_event(
            user_id=111,
            event_dt="2025-12-25T18:00:00+03:00",
            activity="Test",
            notes=None,
            path=db_path,
        )
        jid = await database.create_job(
            event_id=eid,
            job_type="hour_before",
            run_dt="2025-12-25T17:00:00+03:00",
            scheduler_job_id="sched_123",
            path=db_path,
        )
        jobs = await database.get_jobs_for_event(eid, path=db_path)
        assert len(jobs) == 1
        assert jobs[0]["scheduler_job_id"] == "sched_123"

    async def test_delete_jobs(self, db_path):
        await database.upsert_user(111, "Europe/Moscow", path=db_path)
        eid = await database.create_event(
            user_id=111,
            event_dt="2025-12-25T18:00:00+03:00",
            activity="Test",
            notes=None,
            path=db_path,
        )
        await database.create_job(eid, "hour_before", "2025-12-25T17:00:00", "j1", path=db_path)
        await database.create_job(eid, "day_before", "2025-12-24T12:00:00", "j2", path=db_path)
        deleted_ids = await database.delete_jobs_for_event(eid, path=db_path)
        assert set(deleted_ids) == {"j1", "j2"}
        remaining = await database.get_jobs_for_event(eid, path=db_path)
        assert len(remaining) == 0

    async def test_get_all_active_jobs(self, db_path):
        await database.upsert_user(111, "Europe/Moscow", path=db_path)
        eid = await database.create_event(
            user_id=111,
            event_dt="2025-12-25T18:00:00+03:00",
            activity="Test",
            notes=None,
            path=db_path,
        )
        await database.create_job(eid, "hour_before", "2025-12-25T17:00:00", "j1", path=db_path)
        all_jobs = await database.get_all_jobs(path=db_path)
        assert len(all_jobs) == 1
        assert all_jobs[0]["event_status"] == "active"

    async def test_done_event_jobs_excluded(self, db_path):
        await database.upsert_user(111, "Europe/Moscow", path=db_path)
        eid = await database.create_event(
            user_id=111,
            event_dt="2025-12-25T18:00:00+03:00",
            activity="Test",
            notes=None,
            path=db_path,
        )
        await database.create_job(eid, "hour_before", "2025-12-25T17:00:00", "j1", path=db_path)
        await database.update_event_status(eid, "done", path=db_path)
        all_jobs = await database.get_all_jobs(path=db_path)
        assert len(all_jobs) == 0
