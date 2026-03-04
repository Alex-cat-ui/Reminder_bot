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

    async def test_get_active_event_for_user_owner_ok(self, db_path):
        await database.upsert_user(111, "Europe/Moscow", path=db_path)
        eid = await database.create_event(
            user_id=111,
            event_dt="2025-12-25T18:00:00+03:00",
            activity="Owner task",
            notes=None,
            path=db_path,
        )
        event = await database.get_active_event_for_user(eid, 111, path=db_path)
        assert event is not None
        assert event["id"] == eid

    async def test_get_active_event_for_user_wrong_owner_none(self, db_path):
        await database.upsert_user(111, "Europe/Moscow", path=db_path)
        await database.upsert_user(222, "Europe/Moscow", path=db_path)
        eid = await database.create_event(
            user_id=111,
            event_dt="2025-12-25T18:00:00+03:00",
            activity="Owner task",
            notes=None,
            path=db_path,
        )
        event = await database.get_active_event_for_user(eid, 222, path=db_path)
        assert event is None

    async def test_get_active_event_for_user_deleted_none(self, db_path):
        await database.upsert_user(111, "Europe/Moscow", path=db_path)
        eid = await database.create_event(
            user_id=111,
            event_dt="2025-12-25T18:00:00+03:00",
            activity="Deleted task",
            notes=None,
            path=db_path,
        )
        await database.update_event_status(eid, "deleted", path=db_path)
        event = await database.get_active_event_for_user(eid, 111, path=db_path)
        assert event is None

    async def test_update_event_datetime_only(self, db_path):
        await database.upsert_user(111, "Europe/Moscow", path=db_path)
        eid = await database.create_event(
            user_id=111,
            event_dt="2025-12-25T18:00:00+03:00",
            activity="Task",
            notes="Note",
            path=db_path,
        )
        await database.update_event_datetime(eid, "2026-01-01T09:30:00+03:00", path=db_path)
        event = await database.get_event(eid, path=db_path)
        assert event["event_dt"] == "2026-01-01T09:30:00+03:00"
        assert event["activity"] == "Task"
        assert event["notes"] == "Note"

    async def test_update_event_activity_only(self, db_path):
        await database.upsert_user(111, "Europe/Moscow", path=db_path)
        eid = await database.create_event(
            user_id=111,
            event_dt="2025-12-25T18:00:00+03:00",
            activity="Old",
            notes="Note",
            path=db_path,
        )
        await database.update_event_activity(eid, "New", path=db_path)
        event = await database.get_event(eid, path=db_path)
        assert event["activity"] == "New"
        assert event["event_dt"] == "2025-12-25T18:00:00+03:00"
        assert event["notes"] == "Note"

    async def test_update_event_notes_only(self, db_path):
        await database.upsert_user(111, "Europe/Moscow", path=db_path)
        eid = await database.create_event(
            user_id=111,
            event_dt="2025-12-25T18:00:00+03:00",
            activity="Task",
            notes="Old note",
            path=db_path,
        )
        await database.update_event_notes(eid, None, path=db_path)
        event = await database.get_event(eid, path=db_path)
        assert event["notes"] is None
        assert event["activity"] == "Task"


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


@pytest.mark.asyncio
class TestUndoAndDuplicates:
    async def test_create_and_get_undo_action(self, db_path):
        await database.upsert_user(111, "Europe/Moscow", path=db_path)
        event_id = await database.create_event(
            user_id=111,
            event_dt="2026-03-10T10:00:00+03:00",
            activity="Workout",
            notes=None,
            path=db_path,
        )

        await database.create_undo_action(
            event_id=event_id,
            user_id=111,
            token="abcdef123456",
            expires_at="2026-03-10T10:15:00",
            path=db_path,
        )
        undo = await database.get_undo_action("abcdef123456", path=db_path)
        assert undo is not None
        assert undo["event_id"] == event_id
        assert undo["status"] == "active"

    async def test_mark_undo_used(self, db_path):
        await database.upsert_user(111, "Europe/Moscow", path=db_path)
        event_id = await database.create_event(
            user_id=111,
            event_dt="2026-03-10T10:00:00+03:00",
            activity="Workout",
            notes=None,
            path=db_path,
        )
        await database.create_undo_action(
            event_id=event_id,
            user_id=111,
            token="abcdef123456",
            expires_at="2026-03-10T10:15:00",
            path=db_path,
        )
        await database.mark_undo_action_used("abcdef123456", "2026-03-10T10:05:00", path=db_path)
        undo = await database.get_undo_action("abcdef123456", path=db_path)
        assert undo["status"] == "used"
        assert undo["used_at"] == "2026-03-10T10:05:00"

    async def test_mark_undo_expired(self, db_path):
        await database.upsert_user(111, "Europe/Moscow", path=db_path)
        event_id = await database.create_event(
            user_id=111,
            event_dt="2026-03-10T10:00:00+03:00",
            activity="Workout",
            notes=None,
            path=db_path,
        )
        await database.create_undo_action(
            event_id=event_id,
            user_id=111,
            token="abcdef123456",
            expires_at="2026-03-10T10:15:00",
            path=db_path,
        )
        await database.mark_undo_action_expired("abcdef123456", path=db_path)
        undo = await database.get_undo_action("abcdef123456", path=db_path)
        assert undo["status"] == "expired"

    async def test_find_duplicate_events(self, db_path):
        await database.upsert_user(111, "Europe/Moscow", path=db_path)
        event_dt = "2026-03-10T10:00:00+03:00"
        first_id = await database.create_event(
            user_id=111,
            event_dt=event_dt,
            activity="Workout",
            notes=None,
            path=db_path,
        )
        await database.create_event(
            user_id=111,
            event_dt=event_dt,
            activity="workout",
            notes=None,
            path=db_path,
        )

        dupes = await database.find_duplicate_events(
            user_id=111,
            event_dt=event_dt,
            activity_norm="workout",
            path=db_path,
        )
        assert len(dupes) == 2

        dupes_excluding_first = await database.find_duplicate_events(
            user_id=111,
            event_dt=event_dt,
            activity_norm="workout",
            exclude_event_id=first_id,
            path=db_path,
        )
        assert len(dupes_excluding_first) == 1


@pytest.mark.asyncio
class TestMetrics:
    async def test_increment_metric_creates_row(self, db_path):
        await database.increment_metric("create_success", day_utc="2026-03-04", path=db_path)
        rows = await database.get_metrics_for_day("2026-03-04", path=db_path)
        assert rows == [{"key": "create_success", "value": 1}]

    async def test_increment_metric_updates_existing_row(self, db_path):
        await database.increment_metric("create_success", day_utc="2026-03-04", path=db_path)
        await database.increment_metric("create_success", day_utc="2026-03-04", path=db_path)
        rows = await database.get_metrics_for_day("2026-03-04", path=db_path)
        assert rows == [{"key": "create_success", "value": 2}]
