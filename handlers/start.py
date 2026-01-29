"""Handler for /start command."""

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton

import db as database

router = Router()

MAIN_MENU = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Напомнить"), KeyboardButton(text="Мои активности на неделю")],
    ],
    resize_keyboard=True,
)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    user_id = message.from_user.id  # type: ignore[union-attr]
    user = await database.get_user(user_id)
    if user is None:
        from . import timezone as tz_mod
        await tz_mod.ask_timezone(message, state)
    else:
        await message.answer("Главное меню:", reply_markup=MAIN_MENU)
