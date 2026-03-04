"""Shared UI text helpers for step screens."""

from __future__ import annotations


def format_step_with_tz(step_text: str, tz_name: str) -> str:
    """Render canonical step header with timezone line."""
    return f"{step_text}\nЧасовой пояс: {tz_name}\n"


def format_time_picker_text(step_text: str, tz_name: str, hour: int, minute: int) -> str:
    """Render canonical time-picker screen text."""
    return f"{format_step_with_tz(step_text, tz_name)}Текущее значение: {hour:02d}:{minute:02d}"
