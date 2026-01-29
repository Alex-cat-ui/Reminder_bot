"""Timezone selection handler."""

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from zoneinfo import ZoneInfo

import db as database
from .start import MAIN_MENU

router = Router()

POPULAR_TZ = [
    "Europe/Moscow",
    "Europe/Kaliningrad",
    "Asia/Yekaterinburg",
    "Asia/Novosibirsk",
    "Asia/Vladivostok",
    "Europe/Kiev",
    "Asia/Almaty",
]


class TZStates(StatesGroup):
    waiting_tz = State()


def _tz_keyboard() -> ReplyKeyboardMarkup:
    rows = [[KeyboardButton(text=tz)] for tz in POPULAR_TZ]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


async def ask_timezone(message: Message, state: FSMContext) -> None:
    await state.set_state(TZStates.waiting_tz)
    await message.answer(
        "Выберите часовой пояс или введите IANA timezone (например Europe/Moscow):",
        reply_markup=_tz_keyboard(),
    )


@router.message(Command("tz"))
async def cmd_tz(message: Message, state: FSMContext) -> None:
    await state.set_state(TZStates.waiting_tz)
    await message.answer(
        "Выберите часовой пояс или введите IANA timezone:",
        reply_markup=_tz_keyboard(),
    )


@router.message(TZStates.waiting_tz)
async def process_tz(message: Message, state: FSMContext) -> None:
    tz_str = message.text.strip() if message.text else ""
    try:
        ZoneInfo(tz_str)
    except (KeyError, ValueError):
        await message.answer("Некорректный timezone. Попробуйте снова.")
        return
    user_id = message.from_user.id  # type: ignore[union-attr]
    await database.upsert_user(user_id, tz_str)
    await state.clear()
    await message.answer(f"Timezone установлен: {tz_str}", reply_markup=MAIN_MENU)
