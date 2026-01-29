"""Tests for weekly bounds calculation."""

from datetime import datetime
from zoneinfo import ZoneInfo

from handlers.weekly import _week_bounds

TZ = ZoneInfo("Europe/Moscow")


class TestWeekBounds:
    def test_monday(self):
        now = datetime(2025, 6, 9, 14, 0, tzinfo=TZ)  # Monday
        start, end = _week_bounds(now)
        assert start.weekday() == 0  # Monday
        assert start.hour == 0 and start.minute == 0
        assert end.weekday() == 6  # Sunday
        assert end.hour == 23 and end.minute == 59

    def test_sunday(self):
        now = datetime(2025, 6, 15, 20, 0, tzinfo=TZ)  # Sunday
        start, end = _week_bounds(now)
        assert start.day == 15  # Still Sunday since we start from today
        assert end.day == 15  # Sunday
        assert end.hour == 23

    def test_wednesday(self):
        now = datetime(2025, 6, 11, 10, 0, tzinfo=TZ)  # Wednesday
        start, end = _week_bounds(now)
        assert start.day == 11
        assert end.weekday() == 6  # Sunday
        assert end.day == 15

    def test_saturday(self):
        now = datetime(2025, 6, 14, 8, 0, tzinfo=TZ)  # Saturday
        start, end = _week_bounds(now)
        assert start.day == 14
        assert end.weekday() == 6  # Sunday
        assert end.day == 15
