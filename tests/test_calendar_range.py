"""Range and boundary tests for calendar callbacks/keyboard."""

from __future__ import annotations

from datetime import date

from handlers.calendar_core import build_date_calendar_kb, parse_calendar_callback


def _find_button(kb, text: str):
    for row in kb.inline_keyboard:
        for btn in row:
            if btn.text == text:
                return btn
    return None


def test_navigation_before_min_blocked():
    sid = "abcdef12"
    min_date = date(2026, 3, 4)
    max_date = date(2028, 3, 3)
    kb = build_date_calendar_kb(sid, 2026, 3, min_date, max_date, today_date=min_date)
    prev_btn = kb.inline_keyboard[0][0]
    assert prev_btn.callback_data == f"cal2:{sid}:noop"


def test_navigation_after_max_blocked():
    sid = "abcdef12"
    min_date = date(2026, 3, 4)
    max_date = date(2028, 3, 3)
    kb = build_date_calendar_kb(sid, 2028, 3, min_date, max_date, today_date=min_date)
    next_btn = kb.inline_keyboard[0][2]
    assert next_btn.callback_data == f"cal2:{sid}:noop"


def test_past_days_in_current_month_are_non_clickable():
    sid = "abcdef12"
    min_date = date(2026, 3, 4)
    max_date = date(2028, 3, 3)
    kb = build_date_calendar_kb(sid, 2026, 3, min_date, max_date, today_date=min_date)

    # Day "1" is before min_date in this month and must be noop.
    day1 = _find_button(kb, "1")
    assert day1 is not None
    assert day1.callback_data == f"cal2:{sid}:noop"


def test_valid_day_has_cal_day_callback():
    sid = "abcdef12"
    min_date = date(2026, 3, 4)
    max_date = date(2028, 3, 3)
    kb = build_date_calendar_kb(sid, 2026, 3, min_date, max_date, today_date=min_date)

    day15 = _find_button(kb, "15")
    assert day15 is not None
    assert day15.callback_data == f"cal2:{sid}:day:20260315"


def test_leap_day_valid_when_in_range():
    sid = "abcdef12"
    min_date = date(2027, 1, 1)
    max_date = date(2028, 12, 31)
    kb = build_date_calendar_kb(sid, 2028, 2, min_date, max_date, today_date=min_date)

    day29 = _find_button(kb, "29")
    assert day29 is not None
    assert day29.callback_data == f"cal2:{sid}:day:20280229"


def test_invalid_nonexistent_date_rejected():
    assert parse_calendar_callback("cal2:abcdef12:day:20260231") is None
