"""Tests for deterministic date/time parser."""

import pytest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from unittest.mock import patch

from date_parser import (
    parse_user_datetime,
    _try_relative_delta,
    _try_weekday,
    _try_named_day,
    _try_absolute_date_formats,
    _try_time_only,
    _parse_time_str,
    ParseResult,
)

TZ = ZoneInfo("Europe/Moscow")
FIXED_NOW = datetime(2025, 6, 10, 14, 0, 0, tzinfo=TZ)  # Tuesday


@pytest.fixture(autouse=True)
def freeze_now():
    with patch("date_parser._now", return_value=FIXED_NOW):
        yield


# ── Absolute formats ──────────────────────────────

class TestAbsoluteFormats:
    def test_dd_mm_yyyy_hh_mm(self):
        r = parse_user_datetime("25.12.2025 18:00", TZ)
        assert r is not None
        assert r.dt.day == 25 and r.dt.month == 12 and r.dt.year == 2025
        assert r.dt.hour == 18 and r.dt.minute == 0
        assert r.has_date and r.has_time

    def test_dd_mm_yy_hh_mm(self):
        r = parse_user_datetime("25.12.25 18:00", TZ)
        assert r is not None
        assert r.dt.year == 2025

    def test_dd_mm_hh_mm(self):
        r = parse_user_datetime("25.12 15:30", TZ)
        assert r is not None
        assert r.dt.month == 12 and r.dt.day == 25
        assert r.dt.hour == 15 and r.dt.minute == 30

    def test_dd_slash_mm_yyyy_hh_mm(self):
        r = parse_user_datetime("25/12/2025 18:00", TZ)
        assert r is not None
        assert r.dt.day == 25 and r.dt.month == 12

    def test_yyyy_mm_dd_hh_mm(self):
        r = parse_user_datetime("2025-12-25 18:00", TZ)
        assert r is not None
        assert r.dt.year == 2025 and r.dt.month == 12 and r.dt.day == 25

    def test_named_month(self):
        r = parse_user_datetime("4 февраля 18:00", TZ)
        assert r is not None
        assert r.dt.month == 2 and r.dt.day == 4
        assert r.dt.hour == 18

    def test_named_month_short_time(self):
        r = parse_user_datetime("4 фев 18", TZ)
        assert r is not None
        assert r.dt.month == 2 and r.dt.day == 4
        assert r.dt.hour == 18

    def test_dd_mm_no_time(self):
        r = parse_user_datetime("25.12", TZ)
        assert r is not None
        assert r.has_date and not r.has_time
        assert r.dt.month == 12 and r.dt.day == 25

    def test_named_month_no_time(self):
        r = parse_user_datetime("4 февраля", TZ)
        assert r is not None
        assert r.has_date and not r.has_time


# ── Relative formats ─────────────────────────────

class TestRelativeFormats:
    def test_cherez_2_chasa(self):
        r = parse_user_datetime("через 2 часа", TZ)
        assert r is not None
        assert r.has_date and r.has_time
        expected = FIXED_NOW + timedelta(hours=2)
        assert abs((r.dt - expected).total_seconds()) < 5

    def test_cherez_90_minut(self):
        r = parse_user_datetime("через 90 минут", TZ)
        assert r is not None
        expected = FIXED_NOW + timedelta(minutes=90)
        assert abs((r.dt - expected).total_seconds()) < 5

    def test_cherez_1ch_30m(self):
        r = parse_user_datetime("через 1ч 30м", TZ)
        assert r is not None
        expected = FIXED_NOW + timedelta(hours=1, minutes=30)
        assert abs((r.dt - expected).total_seconds()) < 5

    def test_cherez_3_dnya(self):
        r = parse_user_datetime("через 3 дня", TZ)
        assert r is not None
        assert r.has_date and not r.has_time
        expected = FIXED_NOW + timedelta(days=3)
        assert r.dt.date() == expected.date()

    def test_cherez_nedelyu(self):
        r = parse_user_datetime("через неделю", TZ)
        assert r is not None
        expected = FIXED_NOW + timedelta(weeks=1)
        assert r.dt.date() == expected.date()

    def test_cherez_2_nedeli(self):
        r = parse_user_datetime("через 2 недели", TZ)
        assert r is not None
        expected = FIXED_NOW + timedelta(weeks=2)
        assert r.dt.date() == expected.date()


# ── Named days ───────────────────────────────────

class TestNamedDays:
    def test_segodnya(self):
        r = parse_user_datetime("сегодня 18:00", TZ)
        assert r is not None
        assert r.dt.date() == FIXED_NOW.date()
        assert r.dt.hour == 18

    def test_zavtra(self):
        r = parse_user_datetime("завтра 09:00", TZ)
        assert r is not None
        expected_date = (FIXED_NOW + timedelta(days=1)).date()
        assert r.dt.date() == expected_date
        assert r.dt.hour == 9

    def test_poslezavtra(self):
        r = parse_user_datetime("послезавтра 12:00", TZ)
        assert r is not None
        expected_date = (FIXED_NOW + timedelta(days=2)).date()
        assert r.dt.date() == expected_date

    def test_zavtra_no_time(self):
        r = parse_user_datetime("завтра", TZ)
        assert r is not None
        assert r.has_date
        # has_time is False when no time specified alongside named day
        # but the parser keeps current time — this is fine
        expected_date = (FIXED_NOW + timedelta(days=1)).date()
        assert r.dt.date() == expected_date

    def test_zavtra_vecherom(self):
        r = parse_user_datetime("завтра вечером", TZ)
        assert r is not None
        assert r.dt.hour == 19
        assert r.has_time


# ── Weekdays ─────────────────────────────────────

class TestWeekdays:
    def test_v_subbotu(self):
        # FIXED_NOW is Tuesday (weekday=1), Saturday=5, so +4 days
        r = parse_user_datetime("в субботу", TZ)
        assert r is not None
        assert r.dt.weekday() == 5  # Saturday
        assert r.has_date and not r.has_time

    def test_v_sleduyushuyu_subbotu(self):
        r = parse_user_datetime("в следующую субботу", TZ)
        assert r is not None
        assert r.dt.weekday() == 5
        # Should be next week's Saturday (at least 7 days away from this week's)
        days_diff = (r.dt.date() - FIXED_NOW.date()).days
        assert days_diff > 4  # more than this week's Saturday

    def test_v_etu_subbotu(self):
        r = parse_user_datetime("в эту субботу", TZ)
        assert r is not None
        assert r.dt.weekday() == 5

    def test_abbreviations(self):
        r = parse_user_datetime("в пн", TZ)
        assert r is not None
        assert r.dt.weekday() == 0

    def test_v_sredu(self):
        r = parse_user_datetime("в среду", TZ)
        assert r is not None
        assert r.dt.weekday() == 2

    def test_v_voskresenye(self):
        r = parse_user_datetime("в воскресенье", TZ)
        assert r is not None
        assert r.dt.weekday() == 6


# ── Time parts ───────────────────────────────────

class TestTimeParts:
    def test_utrom(self):
        r = parse_user_datetime("завтра утром", TZ)
        assert r is not None
        assert r.dt.hour == 9

    def test_dnem(self):
        r = parse_user_datetime("завтра днём", TZ)
        assert r is not None
        assert r.dt.hour == 14

    def test_vecherom(self):
        r = parse_user_datetime("завтра вечером", TZ)
        assert r is not None
        assert r.dt.hour == 19

    def test_nochyu(self):
        r = parse_user_datetime("завтра ночью", TZ)
        assert r is not None
        assert r.dt.hour == 23


# ── "в N" format ─────────────────────────────────

class TestTimeFormats:
    def test_v_4(self):
        # "в 4" -> 16:00 (PM assumed for 1-11)
        parsed = _parse_time_str("в 4", FIXED_NOW, TZ)
        assert parsed == (16, 0)

    def test_4_utra(self):
        parsed = _parse_time_str("4 утра", FIXED_NOW, TZ)
        assert parsed == (4, 0)

    def test_4_am(self):
        parsed = _parse_time_str("4 am", FIXED_NOW, TZ)
        assert parsed == (4, 0)

    def test_4_pm(self):
        parsed = _parse_time_str("4 pm", FIXED_NOW, TZ)
        assert parsed == (16, 0)

    def test_16_00(self):
        parsed = _parse_time_str("16:00", FIXED_NOW, TZ)
        assert parsed == (16, 0)


# ── Negative cases ───────────────────────────────

class TestNegativeCases:
    def test_garbage(self):
        r = parse_user_datetime("абвгдежз", TZ)
        assert r is None

    def test_empty(self):
        r = parse_user_datetime("", TZ)
        assert r is None

    def test_invalid_date(self):
        r = parse_user_datetime("32.13.2025 18:00", TZ)
        assert r is None

    def test_past_date_detected(self):
        """Parser should return a result; the wizard checks if it's in the past."""
        r = parse_user_datetime("01.01.2020 10:00", TZ)
        assert r is not None
        # The datetime should be in the past (wizard rejects it)
        assert r.dt < FIXED_NOW


# ── Has date / has time flags ────────────────────

class TestParseFlags:
    def test_date_only_has_no_time(self):
        r = parse_user_datetime("25.12", TZ)
        assert r is not None
        assert r.has_date is True
        assert r.has_time is False

    def test_full_has_both(self):
        r = parse_user_datetime("25.12.2025 18:00", TZ)
        assert r is not None
        assert r.has_date is True
        assert r.has_time is True

    def test_relative_hours_has_both(self):
        r = parse_user_datetime("через 2 часа", TZ)
        assert r is not None
        assert r.has_date is True
        assert r.has_time is True

    def test_relative_days_has_date_no_time(self):
        r = parse_user_datetime("через 3 дня", TZ)
        assert r is not None
        assert r.has_date is True
        assert r.has_time is False


# ── Minute-level parsing ─────────────────────────

class TestMinuteLevelRelative:
    def test_cherez_15_minut(self):
        r = parse_user_datetime("через 15 минут", TZ)
        assert r is not None
        expected = FIXED_NOW + timedelta(minutes=15)
        assert abs((r.dt - expected).total_seconds()) < 5

    def test_cherez_1_minutu(self):
        r = parse_user_datetime("через 1 минуту", TZ)
        assert r is not None
        expected = FIXED_NOW + timedelta(minutes=1)
        assert abs((r.dt - expected).total_seconds()) < 5

    def test_cherez_2_chasa_15_minut(self):
        r = parse_user_datetime("через 2 часа 15 минут", TZ)
        assert r is not None
        expected = FIXED_NOW + timedelta(hours=2, minutes=15)
        assert abs((r.dt - expected).total_seconds()) < 5

    def test_cherez_1ch_20m(self):
        r = parse_user_datetime("через 1ч 20м", TZ)
        assert r is not None
        expected = FIXED_NOW + timedelta(hours=1, minutes=20)
        assert abs((r.dt - expected).total_seconds()) < 5

    def test_cherez_2ch_5min(self):
        r = parse_user_datetime("через 2ч 5мин", TZ)
        assert r is not None
        expected = FIXED_NOW + timedelta(hours=2, minutes=5)
        assert abs((r.dt - expected).total_seconds()) < 5

    def test_cherez_40_minut(self):
        r = parse_user_datetime("через 40 минут", TZ)
        assert r is not None
        expected = FIXED_NOW + timedelta(minutes=40)
        assert abs((r.dt - expected).total_seconds()) < 5

    def test_cherez_40_min(self):
        r = parse_user_datetime("через 40 мин", TZ)
        assert r is not None
        expected = FIXED_NOW + timedelta(minutes=40)
        assert abs((r.dt - expected).total_seconds()) < 5

    def test_cherez_polchasa(self):
        r = parse_user_datetime("через полчаса", TZ)
        assert r is not None
        expected = FIXED_NOW + timedelta(minutes=30)
        assert abs((r.dt - expected).total_seconds()) < 5

    def test_cherez_poltora_chasa(self):
        r = parse_user_datetime("через полтора часа", TZ)
        assert r is not None
        expected = FIXED_NOW + timedelta(hours=1, minutes=30)
        assert abs((r.dt - expected).total_seconds()) < 5


class TestMinuteLevelAbsolute:
    def test_v_18_15_colon(self):
        r = parse_user_datetime("в 18:15", TZ)
        assert r is not None
        assert r.dt.hour == 18 and r.dt.minute == 15

    def test_18_15_colon(self):
        r = parse_user_datetime("18:15", TZ)
        assert r is not None
        assert r.dt.hour == 18 and r.dt.minute == 15

    def test_v_18_15_space(self):
        r = parse_user_datetime("в 18 15", TZ)
        assert r is not None
        assert r.dt.hour == 18 and r.dt.minute == 15

    def test_18_15_space(self):
        r = parse_user_datetime("18 15", TZ)
        assert r is not None
        assert r.dt.hour == 18 and r.dt.minute == 15


class TestMinuteLevelMixed:
    def test_v_subbotu_v_18_30(self):
        r = parse_user_datetime("в субботу в 18:30", TZ)
        assert r is not None
        assert r.dt.weekday() == 5
        assert r.dt.hour == 18 and r.dt.minute == 30

    def test_4_fevralya_v_19_45(self):
        r = parse_user_datetime("4 февраля в 19:45", TZ)
        assert r is not None
        assert r.dt.month == 2 and r.dt.day == 4
        assert r.dt.hour == 19 and r.dt.minute == 45

    def test_04_02_18_05(self):
        r = parse_user_datetime("04.02 18:05", TZ)
        assert r is not None
        assert r.dt.month == 2 and r.dt.day == 4
        assert r.dt.hour == 18 and r.dt.minute == 5


class TestMinuteValidation:
    def test_invalid_minutes_75(self):
        r = parse_user_datetime("в 18:75", TZ)
        assert r is None

    def test_invalid_hours_25(self):
        r = parse_user_datetime("в 25:00", TZ)
        assert r is None

    def test_invalid_minutes_60(self):
        r = parse_user_datetime("в 18:60", TZ)
        assert r is None

    def test_default_minutes_zero(self):
        """When only hour given, minutes default to :00."""
        parsed = _parse_time_str("в 18", FIXED_NOW, TZ)
        assert parsed is not None
        assert parsed == (18, 0)

    def test_minutes_preserved(self):
        """When both hour and minute given, minutes are NOT overridden."""
        r = parse_user_datetime("завтра 18:45", TZ)
        assert r is not None
        assert r.dt.hour == 18 and r.dt.minute == 45
