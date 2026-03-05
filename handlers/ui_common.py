"""Shared UI text helpers for step screens."""

from __future__ import annotations


def format_step_with_tz(step_text: str, tz_name: str) -> str:
    """Render canonical step header without displaying timezone to user."""
    _ = tz_name
    return f"{step_text}\n"


def format_time_picker_text(step_text: str, tz_name: str, hour: int, minute: int) -> str:
    """Render canonical time-picker screen text."""
    return f"{format_step_with_tz(step_text, tz_name)}Текущее значение: {hour:02d}:{minute:02d}"
