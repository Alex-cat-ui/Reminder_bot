"""Handler for 'Мои активности на неделю'."""

from datetime import datetime, timedelta

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from .task_browser import start_tasks_browser

router = Router()


def _week_bounds(now: datetime) -> tuple[datetime, datetime]:
    """Return rolling window bounds: [now, now + 7 days]."""
    return now, now + timedelta(days=7)


@router.message(F.text == "Мои активности на неделю")
async def show_week(message: Message, state: FSMContext) -> None:
    await start_tasks_browser(message, state, default_filter="week")
