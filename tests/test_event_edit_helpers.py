"""Tests for event edit callback parsing helpers."""

from handlers.event_edit import parse_evt_callback
from handlers.calendar_core import parse_calendar_callback_with_event, build_date_calendar_kb
from datetime import date


def test_parse_evt_callback_edit_valid():
    parsed = parse_evt_callback("evt:edit:42")
    assert parsed == ("edit", 42, None)


def test_parse_evt_callback_invalid():
    assert parse_evt_callback("evt:unknown:42") is None
    assert parse_evt_callback("evt:edit:notint") is None


def test_parse_edtcal_day_valid():
    parsed = parse_calendar_callback_with_event("edtcal2:abcdef12:day:20270105:42", prefix="edtcal2")
    assert parsed is not None
    kind, payload = parsed
    assert kind == "day"
    assert payload["event_id"] == 42
    assert payload["date"].isoformat() == "2027-01-05"


def test_parse_edtcal_invalid_date():
    parsed = parse_calendar_callback_with_event("edtcal2:abcdef12:day:20270231:42", prefix="edtcal2")
    assert parsed is None


def test_edit_calendar_callback_contains_event_id():
    sid = "abcdef12"
    kb = build_date_calendar_kb(
        sid,
        2027,
        1,
        date(2027, 1, 1),
        date(2028, 1, 1),
        prefix="edtcal2",
        tail_parts=("42",),
    )

    found = False
    for row in kb.inline_keyboard:
        for btn in row:
            cb = btn.callback_data or ""
            if cb.startswith("edtcal2:") and cb.endswith(":42"):
                found = True
                break
        if found:
            break

    assert found
