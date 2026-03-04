"""Tests for unified preview formatter."""

from datetime import datetime
from zoneinfo import ZoneInfo

from handlers.texts import format_event_preview


def test_preview_contains_absolute_datetime_and_timezone():
    dt = datetime(2026, 7, 2, 18, 30, tzinfo=ZoneInfo("Europe/Moscow"))
    text = format_event_preview(
        dt=dt,
        activity="Тренировка",
        mode="create",
    )
    assert "02.07.2026 18:30" in text
    assert "(Europe/Moscow)" not in text
    assert "Активность: Тренировка" in text


def test_preview_contains_only_datetime_and_activity():
    dt = datetime(2026, 7, 2, 18, 30, tzinfo=ZoneInfo("Europe/Moscow"))
    text = format_event_preview(
        dt=dt,
        activity="Тренировка",
        mode="edit",
    )
    assert "Заметки" not in text
    assert "(Europe/Moscow)" not in text
    assert "Проверьте изменения:" in text
