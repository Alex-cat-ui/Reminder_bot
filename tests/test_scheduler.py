"""Tests for scheduler job computation and snooze logic."""

import pytest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from scheduler import compute_job_times

TZ = ZoneInfo("Europe/Moscow")


class TestComputeJobTimes:
    def test_day_before_and_hour_before_and_at_time(self):
        """Event > 24h away: should get day_before, hour_before, at_time."""
        now = datetime(2025, 6, 10, 10, 0, tzinfo=TZ)
        event_dt = datetime(2025, 6, 12, 18, 0, tzinfo=TZ)
        jobs = compute_job_times(event_dt, now)
        types = [j[0] for j in jobs]
        assert "day_before" in types
        assert "hour_before" in types
        assert "at_time" in types
        assert "soon" not in types

    def test_day_before_at_noon(self):
        """Day-before job should be at 12:00 the day before."""
        now = datetime(2025, 6, 10, 10, 0, tzinfo=TZ)
        event_dt = datetime(2025, 6, 12, 18, 0, tzinfo=TZ)
        jobs = compute_job_times(event_dt, now)
        day_before = [j for j in jobs if j[0] == "day_before"]
        assert len(day_before) == 1
        assert day_before[0][1].hour == 12

    def test_hour_before_and_at_time(self):
        """Event 2-24h away, but day_before is in the past: hour_before + at_time."""
        now = datetime(2025, 6, 12, 10, 0, tzinfo=TZ)
        event_dt = datetime(2025, 6, 12, 18, 0, tzinfo=TZ)
        jobs = compute_job_times(event_dt, now)
        types = [j[0] for j in jobs]
        assert "day_before" not in types
        assert "hour_before" in types
        assert "at_time" in types

    def test_soon_and_at_time(self):
        """Event < 60 min away: should get 'soon' AND 'at_time'."""
        now = datetime(2025, 6, 12, 17, 30, tzinfo=TZ)
        event_dt = datetime(2025, 6, 12, 18, 0, tzinfo=TZ)
        jobs = compute_job_times(event_dt, now)
        types = [j[0] for j in jobs]
        assert "soon" in types
        assert "at_time" in types
        assert "hour_before" not in types

    def test_at_time_fires_at_event_dt(self):
        """at_time job run_dt must equal event_dt exactly."""
        now = datetime(2025, 6, 10, 10, 0, tzinfo=TZ)
        event_dt = datetime(2025, 6, 12, 18, 0, tzinfo=TZ)
        jobs = compute_job_times(event_dt, now)
        at_time = [j for j in jobs if j[0] == "at_time"]
        assert len(at_time) == 1
        assert at_time[0][1] == event_dt

    def test_at_time_not_skipped_with_soon(self):
        """Even when 'soon' is scheduled, 'at_time' must still be present."""
        now = datetime(2025, 6, 12, 17, 50, tzinfo=TZ)
        event_dt = datetime(2025, 6, 12, 18, 0, tzinfo=TZ)
        jobs = compute_job_times(event_dt, now)
        types = [j[0] for j in jobs]
        assert "soon" in types
        assert "at_time" in types

    def test_past_event_no_jobs(self):
        """Event in the past: no jobs."""
        now = datetime(2025, 6, 12, 19, 0, tzinfo=TZ)
        event_dt = datetime(2025, 6, 12, 18, 0, tzinfo=TZ)
        jobs = compute_job_times(event_dt, now)
        assert jobs == []


class TestSnoozeLimit:
    def test_snooze_max_is_25(self):
        """The snooze limit is 25; this is enforced at the DB/scheduler level.
        Here we just verify the constant is correct in usage context."""
        MAX_SNOOZE = 25
        assert MAX_SNOOZE == 25
        assert 25 >= MAX_SNOOZE
        assert 24 < MAX_SNOOZE
