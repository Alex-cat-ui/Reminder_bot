"""Inline pseudo-roller time picker helpers."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

_SID_RE = re.compile(r"^[0-9a-f]{8}$")


def picker_initial_now(tz_name: str) -> tuple[int, int]:
    now = datetime.now(ZoneInfo(tz_name))
    return now.hour, now.minute


def picker_initial_now_plus_1h(tz_name: str) -> tuple[int, int]:
    now = datetime.now(ZoneInfo(tz_name)) + timedelta(hours=1)
    return now.hour, now.minute


def apply_picker_step(hour: int, minute: int, action: str, value: str | None = None) -> tuple[int, int]:
    if action == "h":
        if value == "minus1":
            hour = (hour - 1) % 24
        elif value == "plus1":
            hour = (hour + 1) % 24
    elif action == "m":
        if value == "minus5":
            minute = (minute - 5) % 60
        elif value == "plus5":
            minute = (minute + 5) % 60
        elif value is not None and value.isdigit():
            minute = int(value)
    return hour, minute


def build_time_picker_kb(sid: str, hour: int, minute: int) -> InlineKeyboardMarkup:
    hh = f"{hour:02d}"
    mm = f"{minute:02d}"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="-1ч", callback_data=f"tmr2:{sid}:h:minus1"),
                InlineKeyboardButton(text=hh, callback_data=f"tmr2:{sid}:noop"),
                InlineKeyboardButton(text="+1ч", callback_data=f"tmr2:{sid}:h:plus1"),
            ],
            [
                InlineKeyboardButton(text="-5м", callback_data=f"tmr2:{sid}:m:minus5"),
                InlineKeyboardButton(text=mm, callback_data=f"tmr2:{sid}:noop"),
                InlineKeyboardButton(text="+5м", callback_data=f"tmr2:{sid}:m:plus5"),
            ],
            [
                InlineKeyboardButton(text="00", callback_data=f"tmr2:{sid}:m:set:00"),
                InlineKeyboardButton(text="15", callback_data=f"tmr2:{sid}:m:set:15"),
                InlineKeyboardButton(text="30", callback_data=f"tmr2:{sid}:m:set:30"),
                InlineKeyboardButton(text="45", callback_data=f"tmr2:{sid}:m:set:45"),
            ],
            [
                InlineKeyboardButton(text="Сейчас+1ч", callback_data=f"tmr2:{sid}:quick:now_plus_1h"),
                InlineKeyboardButton(text="Готово", callback_data=f"tmr2:{sid}:ok"),
                InlineKeyboardButton(text="Отмена", callback_data=f"tmr2:{sid}:cancel"),
            ],
        ]
    )


def parse_time_picker_callback(data: str) -> tuple[str, dict] | None:
    parts = data.split(":")
    if len(parts) < 3 or parts[0] != "tmr2":
        return None

    sid = parts[1]
    if _SID_RE.match(sid) is None:
        return None

    tag = parts[2]
    if tag in {"noop", "ok", "cancel"} and len(parts) == 3:
        return tag, {"sid": sid}

    if tag == "h" and len(parts) == 4 and parts[3] in {"minus1", "plus1"}:
        return "h", {"sid": sid, "value": parts[3]}

    if tag == "m" and len(parts) == 4 and parts[3] in {"minus5", "plus5"}:
        return "m", {"sid": sid, "value": parts[3]}

    if tag == "m" and len(parts) == 5 and parts[3] == "set" and parts[4] in {"00", "15", "30", "45"}:
        return "m", {"sid": sid, "value": parts[4]}

    if tag == "quick" and len(parts) == 4 and parts[3] == "now_plus_1h":
        return "quick", {"sid": sid, "value": parts[3]}

    return None
