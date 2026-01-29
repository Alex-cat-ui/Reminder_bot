"""Deterministic date/time parser for Russian free-text input.

No LLM. Only regex + dateparser + manual rules.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from dataclasses import dataclass

import dateparser

WEEKDAY_MAP: dict[str, int] = {
    "понедельник": 0, "пн": 0,
    "вторник": 1, "вт": 1,
    "среда": 2, "ср": 2, "среду": 2,
    "четверг": 3, "чт": 3, "чтв": 3,
    "пятница": 4, "пт": 4, "пятницу": 4,
    "суббота": 5, "сб": 5, "суб": 5, "субботу": 5,
    "воскресенье": 6, "вс": 6, "воскр": 6, "воскресение": 6,
}

MONTH_MAP: dict[str, int] = {
    "января": 1, "янв": 1, "январь": 1,
    "февраля": 2, "фев": 2, "февраль": 2,
    "марта": 3, "мар": 3, "март": 3,
    "апреля": 4, "апр": 4, "апрель": 4,
    "мая": 5, "май": 5,
    "июня": 6, "июн": 6, "июнь": 6,
    "июля": 7, "июл": 7, "июль": 7,
    "августа": 8, "авг": 8, "август": 8,
    "сентября": 9, "сен": 9, "сент": 9, "сентябрь": 9,
    "октября": 10, "окт": 10, "октябрь": 10,
    "ноября": 11, "ноя": 11, "нояб": 11, "ноябрь": 11,
    "декабря": 12, "дек": 12, "декабрь": 12,
}

PART_OF_DAY: dict[str, int] = {
    "утром": 9, "утра": 9,
    "днём": 14, "днем": 14, "дня": 14,
    "вечером": 19, "вечера": 19,
    "ночью": 23, "ночи": 23,
}


@dataclass
class ParseResult:
    dt: datetime  # tz-aware
    has_date: bool
    has_time: bool


def _now(tz: ZoneInfo) -> datetime:
    return datetime.now(tz)


def _normalize_text(text: str) -> str:
    """Normalize space-separated time like '18 15' → '18:15'."""
    t = text.strip()
    if t.lower().startswith("через"):
        return t

    def _replace_time(m: re.Match) -> str:
        h, mi = int(m.group(1)), int(m.group(2))
        if 0 <= h <= 23 and 0 <= mi <= 59:
            return f"{m.group(1)}:{m.group(2)}"
        return m.group(0)

    return re.sub(r"(\d{1,2})\s+(\d{2})\s*$", _replace_time, t)


WORD_TO_NUM: dict[str, int] = {
    "одну": 1, "одна": 1, "один": 1,
    "две": 2, "два": 2, "двух": 2,
    "три": 3, "трёх": 3, "трех": 3,
    "четыре": 4, "четырёх": 4, "четырех": 4,
    "пять": 5, "пяти": 5,
    "шесть": 6, "шести": 6,
    "семь": 7, "семи": 7,
    "восемь": 8, "восьми": 8,
    "девять": 9, "девяти": 9,
    "десять": 10, "десяти": 10,
    "пятнадцать": 15, "пятнадцати": 15,
    "двадцать": 20, "двадцати": 20,
    "тридцать": 30, "тридцати": 30,
    "сорок": 40, "сорока": 40,
    "пятьдесят": 50, "пятидесяти": 50,
}


def _try_relative_delta(text: str, now: datetime, tz: ZoneInfo) -> ParseResult | None:
    """Handle: через N часов/минут/дней/недель, через 1ч 30м, через полчаса."""
    t = text.lower().strip()

    # через минуту / через минутку
    if re.match(r"через\s+минут(у|ку)$", t):
        dt = now + timedelta(minutes=1)
        return ParseResult(dt=dt, has_date=True, has_time=True)

    # через полчаса
    if re.match(r"через\s+полчаса$", t):
        dt = now + timedelta(minutes=30)
        return ParseResult(dt=dt, has_date=True, has_time=True)

    # через полтора часа
    if re.match(r"через\s+полтора\s+часа$", t):
        dt = now + timedelta(hours=1, minutes=30)
        return ParseResult(dt=dt, has_date=True, has_time=True)

    # через 1ч 30м / через 1ч30м
    m = re.match(r"через\s+(\d+)\s*ч(?:ас(?:а|ов)?)?\s*(\d+)\s*м(?:ин(?:ут[ауы]?)?)?$", t)
    if m:
        hours, mins = int(m.group(1)), int(m.group(2))
        dt = now + timedelta(hours=hours, minutes=mins)
        return ParseResult(dt=dt, has_date=True, has_time=True)

    # через N минут / через N мин / через N минуту / через N минуты
    m = re.match(r"через\s+(\d+)\s*мин(?:ут[ауы]?)?\.?$", t)
    if m:
        dt = now + timedelta(minutes=int(m.group(1)))
        return ParseResult(dt=dt, has_date=True, has_time=True)

    # через <слово> минут (две минуты, пять минут)
    m = re.match(r"через\s+(\S+)\s+мин(?:ут[ауы]?)?\.?$", t)
    if m:
        word = m.group(1)
        if word in WORD_TO_NUM:
            dt = now + timedelta(minutes=WORD_TO_NUM[word])
            return ParseResult(dt=dt, has_date=True, has_time=True)

    # через N часов / через N час / через N ч
    m = re.match(r"через\s+(\d+)\s*(?:час(?:а|ов)?|ч)$", t)
    if m:
        dt = now + timedelta(hours=int(m.group(1)))
        return ParseResult(dt=dt, has_date=True, has_time=True)

    # через N дней
    m = re.match(r"через\s+(\d+)\s*(?:день|дня|дней)$", t)
    if m:
        dt = now + timedelta(days=int(m.group(1)))
        return ParseResult(dt=dt, has_date=True, has_time=False)

    # через неделю
    m = re.match(r"через\s+неделю$", t)
    if m:
        dt = now + timedelta(weeks=1)
        return ParseResult(dt=dt, has_date=True, has_time=False)

    # через N недель
    m = re.match(r"через\s+(\d+)\s*недел[ьюи]$", t)
    if m:
        dt = now + timedelta(weeks=int(m.group(1)))
        return ParseResult(dt=dt, has_date=True, has_time=False)

    return None


def _try_weekday(text: str, now: datetime, tz: ZoneInfo) -> ParseResult | None:
    """Handle: в субботу, в следующую субботу, в эту субботу."""
    t = text.lower().strip()

    next_week = False
    this_week = False
    day_name: str | None = None

    # в следующую субботу / в следующий понедельник
    m = re.match(r"в\s+следующ(?:ую|ий|ее)\s+(\S+)", t)
    if m:
        next_week = True
        day_name = m.group(1)

    if not day_name:
        m = re.match(r"в\s+эт(?:у|от|о)\s+(\S+)", t)
        if m:
            this_week = True
            day_name = m.group(1)

    if not day_name:
        m = re.match(r"в\s+(\S+)", t)
        if m:
            day_name = m.group(1)

    if not day_name:
        # bare weekday name or abbreviation
        if t in WEEKDAY_MAP:
            day_name = t

    if day_name is None or day_name not in WEEKDAY_MAP:
        return None

    target_wd = WEEKDAY_MAP[day_name]
    current_wd = now.weekday()

    if next_week:
        days_ahead = (target_wd - current_wd) % 7 + 7
    elif this_week:
        days_ahead = (target_wd - current_wd) % 7
        if days_ahead == 0:
            days_ahead = 0  # today
    else:
        days_ahead = (target_wd - current_wd) % 7
        if days_ahead == 0:
            days_ahead = 7

    dt = now + timedelta(days=days_ahead)
    dt = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    return ParseResult(dt=dt, has_date=True, has_time=False)


def _try_named_day(text: str, now: datetime, tz: ZoneInfo) -> ParseResult | None:
    """Handle: сегодня, завтра, послезавтра with optional time."""
    t = text.lower().strip()

    day_offset: int | None = None
    time_part: str = ""

    for word, offset in [("послезавтра", 2), ("завтра", 1), ("сегодня", 0)]:
        if t.startswith(word):
            day_offset = offset
            time_part = t[len(word):].strip()
            break

    if day_offset is None:
        return None

    dt = now + timedelta(days=day_offset)
    dt = dt.replace(second=0, microsecond=0)

    has_time = False
    if time_part:
        parsed_time = _parse_time_str(time_part, now, tz)
        if parsed_time is not None:
            dt = dt.replace(hour=parsed_time[0], minute=parsed_time[1])
            has_time = True

    if not has_time:
        dt = dt.replace(hour=now.hour, minute=now.minute)

    return ParseResult(dt=dt, has_date=True, has_time=has_time)


def _parse_time_str(text: str, now: datetime, tz: ZoneInfo) -> tuple[int, int] | None:
    """Parse a time string fragment and return (hour, minute)."""
    t = text.strip().lower()

    # part of day
    if t in PART_OF_DAY:
        return (PART_OF_DAY[t], 0)

    # HH:MM
    m = re.match(r"(\d{1,2}):(\d{2})$", t)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        if 0 <= h <= 23 and 0 <= mi <= 59:
            return (h, mi)

    # "в HH:MM"
    m = re.match(r"в\s+(\d{1,2}):(\d{2})$", t)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        if 0 <= h <= 23 and 0 <= mi <= 59:
            return (h, mi)

    # "в N" / "N часов" -> PM if 1-11
    m = re.match(r"(?:в\s+)?(\d{1,2})\s*(?:час(?:а|ов)?)?$", t)
    if m:
        h = int(m.group(1))
        if 1 <= h <= 11:
            return (h + 12, 0)  # assume PM
        elif 0 <= h <= 23:
            return (h, 0)

    # N утра / N am
    m = re.match(r"(\d{1,2})\s*(?:утра|am)$", t)
    if m:
        h = int(m.group(1))
        if 1 <= h <= 12:
            return (h if h != 12 else 0, 0)

    # N вечера / N pm / N дня / N ночи
    m = re.match(r"(\d{1,2})\s*(?:вечера|дня|pm)$", t)
    if m:
        h = int(m.group(1))
        if 1 <= h <= 11:
            return (h + 12, 0)
        elif h == 12:
            return (12, 0)

    m = re.match(r"(\d{1,2})\s*(?:ночи)$", t)
    if m:
        h = int(m.group(1))
        if 1 <= h <= 4:
            return (h, 0)
        elif h == 12:
            return (0, 0)

    # "HH" bare number interpreted as hour in time-only context
    m = re.match(r"(\d{1,2})$", t)
    if m:
        h = int(m.group(1))
        if 0 <= h <= 23:
            if 1 <= h <= 11:
                return (h + 12, 0)
            return (h, 0)

    return None


def _try_absolute_date_formats(text: str, now: datetime, tz: ZoneInfo) -> ParseResult | None:
    """Handle explicit date formats."""
    t = text.strip()

    # DD.MM.YYYY HH:MM or DD.MM.YY HH:MM
    m = re.match(r"(\d{1,2})[./](\d{1,2})[./](\d{2,4})\s+(\d{1,2}):(\d{2})$", t)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        h, mi = int(m.group(4)), int(m.group(5))
        if y < 100:
            y += 2000
        try:
            dt = datetime(y, mo, d, h, mi, tzinfo=tz)
            return ParseResult(dt=dt, has_date=True, has_time=True)
        except ValueError:
            return None

    # YYYY-MM-DD HH:MM
    m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{2})$", t)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        h, mi = int(m.group(4)), int(m.group(5))
        try:
            dt = datetime(y, mo, d, h, mi, tzinfo=tz)
            return ParseResult(dt=dt, has_date=True, has_time=True)
        except ValueError:
            return None

    # DD.MM HH:MM (no year)
    m = re.match(r"(\d{1,2})[./](\d{1,2})\s+(\d{1,2}):(\d{2})$", t)
    if m:
        d, mo = int(m.group(1)), int(m.group(2))
        h, mi = int(m.group(3)), int(m.group(4))
        y = now.year
        try:
            dt = datetime(y, mo, d, h, mi, tzinfo=tz)
            if dt < now:
                dt = dt.replace(year=y + 1)
            return ParseResult(dt=dt, has_date=True, has_time=True)
        except ValueError:
            return None

    # DD.MM (no year, no time)
    m = re.match(r"(\d{1,2})[./](\d{1,2})$", t)
    if m:
        d, mo = int(m.group(1)), int(m.group(2))
        y = now.year
        try:
            dt = datetime(y, mo, d, 0, 0, tzinfo=tz)
            if dt.date() < now.date():
                dt = dt.replace(year=y + 1)
            return ParseResult(dt=dt, has_date=True, has_time=False)
        except ValueError:
            return None

    # "4 февраля 18:00" or "4 фев 18" or "4 февраля в 19:45"
    m = re.match(r"(\d{1,2})\s+([а-яё]+)\s+(?:в\s+)?(\d{1,2})(?::(\d{2}))?$", t.lower())
    if m:
        d = int(m.group(1))
        month_str = m.group(2)
        h = int(m.group(3))
        mi = int(m.group(4)) if m.group(4) else 0
        if month_str in MONTH_MAP:
            mo = MONTH_MAP[month_str]
            y = now.year
            try:
                dt = datetime(y, mo, d, h, mi, tzinfo=tz)
                if dt < now:
                    dt = dt.replace(year=y + 1)
                return ParseResult(dt=dt, has_date=True, has_time=True)
            except ValueError:
                return None

    # "4 февраля" (day month_name, no time)
    m = re.match(r"(\d{1,2})\s+([а-яё]+)$", t.lower())
    if m:
        d = int(m.group(1))
        month_str = m.group(2)
        if month_str in MONTH_MAP:
            mo = MONTH_MAP[month_str]
            y = now.year
            try:
                dt = datetime(y, mo, d, 0, 0, tzinfo=tz)
                if dt.date() < now.date():
                    dt = dt.replace(year=y + 1)
                return ParseResult(dt=dt, has_date=True, has_time=False)
            except ValueError:
                return None

    return None


def _try_time_only(text: str, now: datetime, tz: ZoneInfo) -> ParseResult | None:
    """Handle time-only input."""
    parsed = _parse_time_str(text.strip().lower(), now, tz)
    if parsed is not None:
        h, mi = parsed
        return ParseResult(
            dt=now.replace(hour=h, minute=mi, second=0, microsecond=0),
            has_date=False,
            has_time=True,
        )
    return None


def _try_weekday_with_time(text: str, now: datetime, tz: ZoneInfo) -> ParseResult | None:
    """Handle: в субботу 18:00, в субботу вечером."""
    t = text.lower().strip()

    # в [следующую|эту]? <weekday> <time_part>
    m = re.match(
        r"(в\s+(?:следующ(?:ую|ий|ее)\s+|эт(?:у|от|о)\s+)?\S+)\s+(.+)$", t
    )
    if m:
        weekday_part = m.group(1)
        time_part = m.group(2)
        wd_result = _try_weekday(weekday_part, now, tz)
        if wd_result:
            parsed_time = _parse_time_str(time_part, now, tz)
            if parsed_time is not None:
                wd_result.dt = wd_result.dt.replace(hour=parsed_time[0], minute=parsed_time[1])
                wd_result.has_time = True
                return wd_result
    return None


def parse_user_datetime(text: str, tz: ZoneInfo) -> ParseResult | None:
    """Main entry point: parse free-text date/time in Russian.

    Returns ParseResult with tz-aware datetime, or None if not recognized.
    """
    now = _now(tz)
    text = _normalize_text(text)

    # Try each parser in order of specificity
    for parser in [
        _try_relative_delta,
        _try_named_day,
        _try_weekday_with_time,
        _try_weekday,
        _try_absolute_date_formats,
        _try_time_only,
    ]:
        result = parser(text, now, tz)
        if result is not None:
            return result

    # Fallback: dateparser
    settings = {
        "TIMEZONE": str(tz),
        "RETURN_AS_TIMEZONE_AWARE": True,
        "PREFER_DATES_FROM": "future",
        "DATE_ORDER": "DMY",
    }
    parsed = dateparser.parse(text, languages=["ru"], settings=settings)  # type: ignore[arg-type]
    if parsed is not None:
        parsed = parsed.astimezone(tz)
        has_time = bool(re.search(r"\d{1,2}:\d{2}", text))
        return ParseResult(dt=parsed, has_date=True, has_time=has_time)

    return None
