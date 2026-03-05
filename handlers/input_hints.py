"""Shared fallback replies for button-only date/time input flows."""

from __future__ import annotations

from aiogram.types import Message

from .texts import MSG_PICK_DATE_WITH_BUTTONS, MSG_PICK_TIME_WITH_BUTTONS


async def reply_pick_date_hint(message: Message) -> None:
    await message.answer(MSG_PICK_DATE_WITH_BUTTONS)


async def reply_pick_time_hint(message: Message) -> None:
    await message.answer(MSG_PICK_TIME_WITH_BUTTONS)
