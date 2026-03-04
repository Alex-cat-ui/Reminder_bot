"""Shared inline calendar/time keyboard helpers."""

from __future__ import annotations

import calendar
import re
import time
import uuid
from datetime import date

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

MONTH_NAMES_RU = [
    "Январь",
    "Февраль",
    "Март",
    "Апрель",
    "Май",
    "Июнь",
    "Июль",
    "Август",
    "Сентябрь",
    "Октябрь",
    "Ноябрь",
    "Декабрь",
]

WEEKDAY_SHORT_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

_SID_RE = re.compile(r"^[0-9a-f]{8}$")
_LAST_CB_TS: dict[int, float] = {}


def new_calendar_session_id() -> str:
    """Return 8-char lowercase hex session id."""
    return uuid.uuid4().hex[:8]


def month_shift(year: int, month: int, delta: int) -> tuple[int, int]:
    """Shift (year, month) by delta months."""
    idx = (year * 12 + (month - 1)) + delta
    new_year = idx // 12
    new_month = idx % 12 + 1
    return new_year, new_month


def _cb(prefix: str, sid: str, *parts: str, tail_parts: tuple[str, ...] = ()) -> str:
    return ":".join([prefix, sid, *parts, *tail_parts])


def build_date_calendar_kb(
    sid: str,
    view_year: int,
    view_month: int,
    min_date: date,
    max_date: date,
    *,
    selected_date: date | None = None,
    today_date: date | None = None,
    prefix: str = "cal2",
    tail_parts: tuple[str, ...] = (),
) -> InlineKeyboardMarkup:
    """Build date keyboard with navigation, quick dates, weekdays and 6 day rows."""
    today = today_date or min_date

    prev_year, prev_month = month_shift(view_year, view_month, -1)
    next_year, next_month = month_shift(view_year, view_month, 1)

    prev_month_start = date(prev_year, prev_month, 1)
    next_month_start = date(next_year, next_month, 1)
    min_month_start = date(min_date.year, min_date.month, 1)
    max_month_start = date(max_date.year, max_date.month, 1)

    can_prev = prev_month_start >= min_month_start
    can_next = next_month_start <= max_month_start

    kb: list[list[InlineKeyboardButton]] = []

    kb.append(
        [
            InlineKeyboardButton(
                text="<",
                callback_data=(
                    _cb(
                        prefix,
                        sid,
                        "nav",
                        "prev",
                        f"{view_year:04d}",
                        f"{view_month:02d}",
                        tail_parts=tail_parts,
                    )
                    if can_prev
                    else _cb(prefix, sid, "noop", tail_parts=tail_parts)
                ),
            ),
            InlineKeyboardButton(
                text=f"{MONTH_NAMES_RU[view_month - 1]} {view_year}",
                callback_data=_cb(prefix, sid, "noop", tail_parts=tail_parts),
            ),
            InlineKeyboardButton(
                text=">",
                callback_data=(
                    _cb(
                        prefix,
                        sid,
                        "nav",
                        "next",
                        f"{view_year:04d}",
                        f"{view_month:02d}",
                        tail_parts=tail_parts,
                    )
                    if can_next
                    else _cb(prefix, sid, "noop", tail_parts=tail_parts)
                ),
            ),
        ]
    )

    kb.append(
        [
            InlineKeyboardButton(
                text="Сегодня",
                callback_data=_cb(prefix, sid, "quick", "today", tail_parts=tail_parts),
            ),
            InlineKeyboardButton(
                text="Завтра",
                callback_data=_cb(prefix, sid, "quick", "tomorrow", tail_parts=tail_parts),
            ),
            InlineKeyboardButton(
                text="+7 дней",
                callback_data=_cb(prefix, sid, "quick", "plus7", tail_parts=tail_parts),
            ),
        ]
    )

    kb.append(
        [
            InlineKeyboardButton(text=wd, callback_data=_cb(prefix, sid, "noop", tail_parts=tail_parts))
            for wd in WEEKDAY_SHORT_RU
        ]
    )

    cal = calendar.Calendar(firstweekday=0)
    weeks = cal.monthdayscalendar(view_year, view_month)
    while len(weeks) < 6:
        weeks.append([0, 0, 0, 0, 0, 0, 0])

    for week in weeks[:6]:
        row: list[InlineKeyboardButton] = []
        for day_num in week:
            if day_num == 0:
                row.append(
                    InlineKeyboardButton(
                        text=" ", callback_data=_cb(prefix, sid, "noop", tail_parts=tail_parts)
                    )
                )
                continue

            cell_date = date(view_year, view_month, day_num)
            label = f"{day_num}"

            if cell_date == today:
                label = f"🟢{day_num}"

            if selected_date is not None and cell_date == selected_date:
                label = f"[{label}]"

            if cell_date < min_date or cell_date > max_date:
                cb_data = _cb(prefix, sid, "noop", tail_parts=tail_parts)
            else:
                cb_data = _cb(
                    prefix,
                    sid,
                    "day",
                    cell_date.strftime("%Y%m%d"),
                    tail_parts=tail_parts,
                )

            row.append(InlineKeyboardButton(text=label, callback_data=cb_data))

        kb.append(row)

    kb.append(
        [
            InlineKeyboardButton(
                text="Отмена",
                callback_data=_cb(prefix, sid, "cancel", tail_parts=tail_parts),
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=kb)


def build_quick_time_kb(
    sid: str,
    *,
    prefix: str = "cal2",
    tail_parts: tuple[str, ...] = (),
) -> InlineKeyboardMarkup:
    """Build quick-time keyboard in HH:MM format and manual option."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="09:00",
                    callback_data=_cb(prefix, sid, "time", "0900", tail_parts=tail_parts),
                ),
                InlineKeyboardButton(
                    text="12:00",
                    callback_data=_cb(prefix, sid, "time", "1200", tail_parts=tail_parts),
                ),
                InlineKeyboardButton(
                    text="18:00",
                    callback_data=_cb(prefix, sid, "time", "1800", tail_parts=tail_parts),
                ),
                InlineKeyboardButton(
                    text="20:00",
                    callback_data=_cb(prefix, sid, "time", "2000", tail_parts=tail_parts),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Ввести вручную",
                    callback_data=_cb(prefix, sid, "time", "manual", tail_parts=tail_parts),
                )
            ],
        ]
    )


def parse_calendar_callback_with_event(
    data: str,
    *,
    prefix: str = "edtcal2",
) -> tuple[str, dict] | None:
    """Parse callback with trailing event_id payload."""
    parts = data.split(":")
    if len(parts) < 4:
        return None
    event_part = parts[-1]
    if not event_part.isdigit():
        return None
    event_id = int(event_part)
    parsed = parse_calendar_callback(":".join(parts[:-1]), prefix=prefix)
    if parsed is None:
        return None
    kind, payload = parsed
    payload["event_id"] = event_id
    return kind, payload


def parse_calendar_callback(data: str, *, prefix: str = "cal2") -> tuple[str, dict] | None:
    """Parse calendar callback payload into (kind, payload)."""
    parts = data.split(":")
    if len(parts) < 3:
        return None
    if parts[0] != prefix:
        return None

    sid = parts[1]
    if _SID_RE.match(sid) is None:
        return None

    tag = parts[2]

    if tag in {"noop", "cancel"} and len(parts) == 3:
        return tag, {"sid": sid}

    if tag == "nav" and len(parts) == 6 and parts[3] in {"prev", "next"}:
        if not (parts[4].isdigit() and parts[5].isdigit()):
            return None
        year = int(parts[4])
        month = int(parts[5])
        if year < 1 or not (1 <= month <= 12):
            return None
        return "nav", {"sid": sid, "direction": parts[3], "year": year, "month": month}

    if tag == "day" and len(parts) == 4:
        ymd = parts[3]
        if len(ymd) != 8 or not ymd.isdigit():
            return None
        y, m, d = int(ymd[:4]), int(ymd[4:6]), int(ymd[6:8])
        try:
            selected = date(y, m, d)
        except ValueError:
            return None
        return "day", {"sid": sid, "date": selected}

    if tag == "quick" and len(parts) == 4 and parts[3] in {"today", "tomorrow", "plus7"}:
        return "quick", {"sid": sid, "value": parts[3]}

    if tag == "time" and len(parts) == 4 and parts[3] in {"0900", "1200", "1800", "2000", "manual"}:
        return "time", {"sid": sid, "value": parts[3]}

    return None


def is_debounced(user_id: int, now_ts: float | None = None) -> bool:
    """Return True if callback should be rejected by per-user debounce window."""
    if now_ts is None:
        now_ts = time.time()

    prev_ts = _LAST_CB_TS.get(user_id)
    _LAST_CB_TS[user_id] = now_ts

    if prev_ts is None:
        return False
    return (now_ts - prev_ts) < 0.35
