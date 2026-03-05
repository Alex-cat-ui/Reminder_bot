"""Shared flow helpers for calendar bounds, quick-date and duplicate decision callbacks."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from .ui_tokens import CANCEL_TEXT, STYLE_DANGER


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


def state_iso_date(data: dict, key: str) -> date | None:
    """Read optional ISO date value from FSM data by key."""
    value = data.get(key)
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def clamp_month_to_bounds(
    year: int,
    month: int,
    *,
    min_date: date,
    max_date: date,
) -> tuple[int, int]:
    """Clamp (year, month) to [min_date.month, max_date.month] range."""
    min_month = (min_date.year, min_date.month)
    max_month = (max_date.year, max_date.month)
    if (year, month) < min_month:
        return min_month
    if (year, month) > max_month:
        return max_month
    return year, month


def build_duplicate_warning_kb(sid: str) -> InlineKeyboardMarkup:
    """Inline keyboard for duplicate warning confirm/cancel."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Сохранить", callback_data=f"dup2:{sid}:save")],
            [InlineKeyboardButton(text=CANCEL_TEXT, callback_data=f"dup2:{sid}:cancel", style=STYLE_DANGER)],
        ]
    )


def parse_duplicate_callback(data: str) -> tuple[str, str] | None:
    """Parse duplicate callback payload into (sid, action)."""
    parts = data.split(":")
    if len(parts) != 3 or parts[0] != "dup2" or parts[2] not in {"save", "cancel"}:
        return None
    return parts[1], parts[2]
