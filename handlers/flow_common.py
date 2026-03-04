"""Shared flow helpers for calendar bounds, quick-date and duplicate decision callbacks."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def calendar_bounds(tz_name: str, *, days_ahead: int = 730) -> tuple[date, date]:
    """Return [today, today + days_ahead] in user timezone."""
    tz = ZoneInfo(tz_name)
    today = datetime.now(tz).date()
    return today, today + timedelta(days=days_ahead)


def quick_date(value: str, today: date) -> date | None:
    """Map quick date token to concrete date."""
    if value == "today":
        return today
    if value == "tomorrow":
        return today + timedelta(days=1)
    if value == "plus7":
        return today + timedelta(days=7)
    return None


def build_duplicate_warning_kb(sid: str) -> InlineKeyboardMarkup:
    """Inline keyboard for duplicate warning confirm/cancel."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Сохранить", callback_data=f"dup2:{sid}:save")],
            [InlineKeyboardButton(text="Отмена", callback_data=f"dup2:{sid}:cancel")],
        ]
    )


def parse_duplicate_callback(data: str) -> tuple[str, str] | None:
    """Parse duplicate callback payload into (sid, action)."""
    parts = data.split(":")
    if len(parts) != 3 or parts[0] != "dup2" or parts[2] not in {"save", "cancel"}:
        return None
    return parts[1], parts[2]
