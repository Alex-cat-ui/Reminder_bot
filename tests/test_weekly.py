"""Tests for rolling-week bounds calculation."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from handlers.weekly import _week_bounds

TZ = ZoneInfo("Europe/Moscow")


class TestWeekBounds:
    def test_monday(self):
        now = datetime(2025, 6, 9, 14, 0, tzinfo=TZ)  # Monday
        start, end = _week_bounds(now)
        assert start == now
        assert end == now + timedelta(days=7)

    def test_sunday(self):
        now = datetime(2025, 6, 15, 20, 0, tzinfo=TZ)  # Sunday
        start, end = _week_bounds(now)
        assert start == now
        assert end == now + timedelta(days=7)

    def test_wednesday(self):
        now = datetime(2025, 6, 11, 10, 0, tzinfo=TZ)  # Wednesday
        start, end = _week_bounds(now)
        assert start == now
        assert end == now + timedelta(days=7)

    def test_saturday(self):
        now = datetime(2025, 6, 14, 8, 0, tzinfo=TZ)  # Saturday
        start, end = _week_bounds(now)
        assert start == now
        assert end == now + timedelta(days=7)
