"""Inline pseudo-roller time picker helpers."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from .ui_tokens import CANCEL_TEXT, DONE_TEXT, STYLE_DANGER, STYLE_PRIMARY, STYLE_SUCCESS

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


def apply_picker_action(
    hour: int,
    minute: int,
    kind: str,
    value: str | None,
    *,
    tz_name: str,
) -> tuple[int, int]:
    """Apply one picker callback action to current HH:MM candidate."""
    if kind == "quick":
        return picker_initial_now_plus_1h(tz_name)
    if kind == "t" and value is not None and len(value) == 4 and value.isdigit():
        return int(value[:2]), int(value[2:])
    return apply_picker_step(hour, minute, kind, value)


def build_time_picker_kb(sid: str, hour: int, minute: int) -> InlineKeyboardMarkup:
    hh = f"{hour:02d}"
    mm = f"{minute:02d}"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="-1ч", callback_data=f"tmr2:{sid}:h:minus1", style=STYLE_SUCCESS),
                InlineKeyboardButton(text=hh, callback_data=f"tmr2:{sid}:noop", style=STYLE_SUCCESS),
                InlineKeyboardButton(text="+1ч", callback_data=f"tmr2:{sid}:h:plus1", style=STYLE_SUCCESS),
            ],
            [
                InlineKeyboardButton(text="-5м", callback_data=f"tmr2:{sid}:m:minus5", style=STYLE_SUCCESS),
                InlineKeyboardButton(text=mm, callback_data=f"tmr2:{sid}:noop", style=STYLE_SUCCESS),
                InlineKeyboardButton(text="+5м", callback_data=f"tmr2:{sid}:m:plus5", style=STYLE_SUCCESS),
            ],
            [
                InlineKeyboardButton(text="00", callback_data=f"tmr2:{sid}:m:set:00", style=STYLE_PRIMARY),
                InlineKeyboardButton(text="15", callback_data=f"tmr2:{sid}:m:set:15", style=STYLE_PRIMARY),
                InlineKeyboardButton(text="30", callback_data=f"tmr2:{sid}:m:set:30", style=STYLE_PRIMARY),
                InlineKeyboardButton(text="45", callback_data=f"tmr2:{sid}:m:set:45", style=STYLE_PRIMARY),
            ],
            [
                InlineKeyboardButton(text="09:00", callback_data=f"tmr2:{sid}:t:set:0900", style=STYLE_PRIMARY),
                InlineKeyboardButton(text="12:00", callback_data=f"tmr2:{sid}:t:set:1200", style=STYLE_PRIMARY),
                InlineKeyboardButton(text="18:00", callback_data=f"tmr2:{sid}:t:set:1800", style=STYLE_PRIMARY),
                InlineKeyboardButton(text="20:00", callback_data=f"tmr2:{sid}:t:set:2000", style=STYLE_PRIMARY),
            ],
            [
                InlineKeyboardButton(text="Сейчас+1ч", callback_data=f"tmr2:{sid}:quick:now_plus_1h"),
                InlineKeyboardButton(text=DONE_TEXT, callback_data=f"tmr2:{sid}:ok", style=STYLE_SUCCESS),
            ],
            [InlineKeyboardButton(text=CANCEL_TEXT, callback_data=f"tmr2:{sid}:cancel", style=STYLE_DANGER)],
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

    if tag == "t" and len(parts) == 5 and parts[3] == "set" and parts[4] in {"0900", "1200", "1800", "2000"}:
        return "t", {"sid": sid, "value": parts[4]}

    return None
