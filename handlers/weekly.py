"""Handler for 'Мои активности на неделю'."""

from datetime import datetime, timedelta

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from .task_browser import start_tasks_browser

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
async def show_week(message: Message, state: FSMContext) -> None:
    await start_tasks_browser(message, state, default_filter="week")
