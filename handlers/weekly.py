"""Handler for 'Мои активности на неделю'."""

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from .task_browser import start_tasks_browser

router = Router()


@router.message(F.text == "Мои активности на неделю")
async def show_week(message: Message, state: FSMContext) -> None:
    await start_tasks_browser(message, state, default_filter="week")
