"""Tests for shared calendar core helpers."""

from __future__ import annotations

import re
from datetime import date

from handlers.calendar_core import (
    build_date_calendar_kb,
    build_quick_time_kb,
    is_debounced,
    month_shift,
    new_calendar_session_id,
    parse_calendar_callback,
)


def _all_buttons(kb):
    for row in kb.inline_keyboard:
        for btn in row:
            yield btn


def test_session_id_length_and_hex():
    sid = new_calendar_session_id()
    assert len(sid) == 8
    assert re.match(r"^[0-9a-f]{8}$", sid)


def test_month_shift_across_year_forward():
    assert month_shift(2026, 12, 1) == (2027, 1)


def test_month_shift_across_year_backward():
    assert month_shift(2026, 1, -1) == (2025, 12)


def test_today_day_has_success_style():
    sid = "abcdef12"
    today = date(2026, 3, 4)
    max_date = date(2028, 3, 3)
    kb = build_date_calendar_kb(
        sid,
        2026,
        3,
        today,
        max_date,
        today_date=today,
    )
    day_buttons = [b for b in _all_buttons(kb) if b.callback_data == f"cal2:{sid}:day:20260304"]
    assert day_buttons
    assert day_buttons[0].text == "4"
    assert day_buttons[0].style == "success"


def test_selected_today_label_format():
    sid = "abcdef12"
    today = date(2026, 3, 4)
    max_date = date(2028, 3, 3)
    kb = build_date_calendar_kb(
        sid,
        2026,
        3,
        today,
        max_date,
        selected_date=today,
        today_date=today,
    )
    day_buttons = [b for b in _all_buttons(kb) if b.callback_data == f"cal2:{sid}:day:20260304"]
    assert day_buttons
    assert day_buttons[0].text == "[4]"
    assert day_buttons[0].style == "success"


def test_quick_dates_callbacks_present():
    sid = "abcdef12"
    today = date(2026, 3, 4)
    max_date = date(2028, 3, 3)
    kb = build_date_calendar_kb(sid, 2026, 3, today, max_date, today_date=today)
    row2 = kb.inline_keyboard[1]
    callbacks = [b.callback_data for b in row2]
    assert callbacks == [
        f"cal2:{sid}:quick:today",
        f"cal2:{sid}:quick:tomorrow",
        f"cal2:{sid}:quick:plus7",
    ]
    assert [b.style for b in row2] == ["success", "primary", "primary"]


def test_weekend_weekday_headers_are_danger():
    sid = "abcdef12"
    today = date(2026, 3, 4)
    max_date = date(2028, 3, 3)
    kb = build_date_calendar_kb(sid, 2026, 3, today, max_date, today_date=today)
    weekday_row = kb.inline_keyboard[2]
    assert [b.text for b in weekday_row] == ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    assert [b.style for b in weekday_row] == [None, None, None, None, None, "danger", "danger"]


def test_quick_times_callbacks_are_hhmm_only():
    sid = "abcdef12"
    kb = build_quick_time_kb(sid)
    row1 = kb.inline_keyboard[0]
    assert [b.text for b in row1] == ["09:00", "12:00", "18:00", "20:00"]
    assert [b.callback_data for b in row1] == [
        f"cal2:{sid}:time:0900",
        f"cal2:{sid}:time:1200",
        f"cal2:{sid}:time:1800",
        f"cal2:{sid}:time:2000",
    ]
    assert kb.inline_keyboard[1][0].text == "Кастомное время"
    assert kb.inline_keyboard[1][0].style == "primary"
    assert kb.inline_keyboard[1][0].callback_data == f"cal2:{sid}:time:picker"
    assert kb.inline_keyboard[2][0].text == "Отмена"
    assert kb.inline_keyboard[2][0].style == "danger"
    assert kb.inline_keyboard[2][0].callback_data == f"cal2:{sid}:cancel"


def test_invalid_session_rejected():
    assert parse_calendar_callback("cal2:INVALID:quick:today") is None


def test_debounce_rejects_second_click_within_350ms():
    user_id = 999123
    assert is_debounced(user_id, now_ts=1000.0) is False
    assert is_debounced(user_id, now_ts=1000.2) is True
    assert is_debounced(user_id, now_ts=1000.6) is False
