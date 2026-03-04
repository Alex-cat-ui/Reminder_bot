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


def test_today_label_has_green_marker():
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
    texts = [b.text for b in _all_buttons(kb)]
    assert "🟢4" in texts


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
    texts = [b.text for b in _all_buttons(kb)]
    assert "[🟢4]" in texts


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
    assert kb.inline_keyboard[1][0].callback_data == f"cal2:{sid}:time:manual"


def test_invalid_session_rejected():
    assert parse_calendar_callback("cal2:INVALID:quick:today") is None


def test_debounce_rejects_second_click_within_350ms():
    user_id = 999123
    assert is_debounced(user_id, now_ts=1000.0) is False
    assert is_debounced(user_id, now_ts=1000.2) is True
    assert is_debounced(user_id, now_ts=1000.6) is False
