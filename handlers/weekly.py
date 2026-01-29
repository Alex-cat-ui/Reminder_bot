"""Handler for 'Мои активности на неделю'."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import Router, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

import db as database

router = Router()


def _week_bounds(now: datetime) -> tuple[datetime, datetime]:
    """Return (monday 00:00, sunday 23:59) for the current week."""
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    # go to start of today, then find Sunday 23:59
    days_until_sunday = 6 - now.weekday()
    end = (start + timedelta(days=days_until_sunday)).replace(
        hour=23, minute=59, second=59, microsecond=0
    )
    return start, end


@router.message(F.text == "Мои активности на неделю")
async def show_week(message: Message) -> None:
    user_id = message.from_user.id  # type: ignore[union-attr]
    user = await database.get_user(user_id)
    if not user:
        await message.answer("Сначала установите часовой пояс: /tz")
        return

    tz = ZoneInfo(user["timezone"])
    now = datetime.now(tz)
    start, end = _week_bounds(now)

    events = await database.get_week_events(
        user_id, start.isoformat(), end.isoformat()
    )

    if not events:
        await message.answer("На этой неделе нет активных напоминаний.")
        return

    for ev in events:
        dt = datetime.fromisoformat(ev["event_dt"])
        dt_str = dt.strftime("%d.%m.%Y %H:%M")
        text = f"Когда: {dt_str}\nАктивность: {ev['activity']}"
        if ev.get("notes"):
            text += f"\nЗаметки:\n{ev['notes']}"

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Удалить",
                        callback_data=f"delete:{ev['id']}",
                    )
                ]
            ]
        )
        await message.answer(text, reply_markup=kb)
