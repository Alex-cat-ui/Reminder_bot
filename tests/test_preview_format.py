"""Tests for unified preview formatter."""

from datetime import datetime
from zoneinfo import ZoneInfo

from handlers.texts import format_event_preview


def test_preview_contains_absolute_datetime_and_timezone():
    dt = datetime(2026, 7, 2, 18, 30, tzinfo=ZoneInfo("Europe/Moscow"))
    text = format_event_preview(
        dt=dt,
        activity="Тренировка",
        notes="Взять форму",
        tz_name="Europe/Moscow",
        mode="create",
    )
    assert "02.07.2026 18:30" in text
    assert "(Europe/Moscow)" in text
    assert "Активность: Тренировка" in text


def test_preview_notes_dash_when_empty():
    dt = datetime(2026, 7, 2, 18, 30, tzinfo=ZoneInfo("Europe/Moscow"))
    text = format_event_preview(
        dt=dt,
        activity="Тренировка",
        notes=None,
        tz_name="Europe/Moscow",
        mode="edit",
    )
    assert "Заметки:\n—" in text
    assert "Проверьте изменения:" in text
