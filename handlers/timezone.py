"""Timezone selection handler."""

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from zoneinfo import ZoneInfo

import db as database
from .start import MAIN_MENU
from .texts import MSG_BAD_TZ, MSG_TZ_CANCELLED, MSG_TZ_SET
from .ui_tokens import is_cancel_text

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
    rows.append([KeyboardButton(text="Отмена")])
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
    if is_cancel_text(message.text):
        await state.clear()
        await message.answer(MSG_TZ_CANCELLED, reply_markup=MAIN_MENU)
        return

    tz_str = message.text.strip() if message.text else ""
    try:
        ZoneInfo(tz_str)
    except (KeyError, ValueError):
        await message.answer(MSG_BAD_TZ)
        return
    user_id = message.from_user.id  # type: ignore[union-attr]
    await database.upsert_user(user_id, tz_str)
    await state.clear()
    await message.answer(MSG_TZ_SET.format(tz=tz_str), reply_markup=MAIN_MENU)
