"""Wizard FSM for creating a new reminder."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
)

import db as database
from date_parser import parse_user_datetime
from notes_fmt import format_notes
from scheduler import schedule_event_jobs
from .start import MAIN_MENU

router = Router()


class WizardStates(StatesGroup):
    waiting_date = State()
    waiting_time_only = State()
    waiting_date_only = State()
    waiting_activity = State()
    waiting_notes = State()
    confirm = State()
    edit_choice = State()


CANCEL_KB = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="Отмена")]],
    resize_keyboard=True,
)


@router.message(F.text == "Напомнить")
async def start_wizard(message: Message, state: FSMContext) -> None:
    user_id = message.from_user.id  # type: ignore[union-attr]
    user = await database.get_user(user_id)
    if not user:
        await message.answer("Сначала установите часовой пояс: /tz")
        return
    await state.set_state(WizardStates.waiting_date)
    await state.update_data(timezone=user["timezone"])
    await message.answer(
        "Введите дату и время (например: завтра 18:00, 25.12 15:30, через 2 часа):",
        reply_markup=CANCEL_KB,
    )


@router.message(WizardStates.waiting_date, F.text == "Отмена")
@router.message(WizardStates.waiting_time_only, F.text == "Отмена")
@router.message(WizardStates.waiting_date_only, F.text == "Отмена")
@router.message(WizardStates.waiting_activity, F.text == "Отмена")
@router.message(WizardStates.waiting_notes, F.text == "Отмена")
@router.message(WizardStates.confirm, F.text == "Отмена")
@router.message(WizardStates.edit_choice, F.text == "Отмена")
async def cancel_wizard(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Создание напоминания отменено.", reply_markup=MAIN_MENU)


@router.message(WizardStates.waiting_date)
async def process_date(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    tz = ZoneInfo(data["timezone"])
    text = message.text or ""

    result = parse_user_datetime(text, tz)
    if result is None:
        await message.answer("Не понял дату/время. Попробуй иначе.")
        return

    now = datetime.now(tz)

    if not result.has_time and result.has_date:
        await state.update_data(partial_date=result.dt.isoformat())
        await state.set_state(WizardStates.waiting_time_only)
        await message.answer("Понял дату. Теперь введите время (например: 18:00, вечером):")
        return

    if result.has_time and not result.has_date:
        await state.update_data(partial_time_h=result.dt.hour, partial_time_m=result.dt.minute)
        await state.set_state(WizardStates.waiting_date_only)
        await message.answer("Понял время. Теперь введите дату (например: завтра, 25.12, в субботу):")
        return

    # Both date and time present
    if result.dt <= now:
        if result.dt.date() < now.date():
            await message.answer("Введи корректную дату")
        else:
            await message.answer("Введи корректное время")
        return

    await state.update_data(event_dt=result.dt.isoformat())
    await state.set_state(WizardStates.waiting_activity)
    await message.answer("Введите активность (1-200 символов):")


@router.message(WizardStates.waiting_time_only)
async def process_time_only(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    tz = ZoneInfo(data["timezone"])
    text = message.text or ""

    from date_parser import _parse_time_str, _now
    now = _now(tz)
    parsed_time = _parse_time_str(text.strip().lower(), now, tz)
    if parsed_time is None:
        await message.answer("Не понял время. Попробуй иначе (например: 18:00, вечером).")
        return

    partial_date = datetime.fromisoformat(data["partial_date"])
    dt = partial_date.replace(hour=parsed_time[0], minute=parsed_time[1], second=0, microsecond=0)

    if dt <= now:
        await message.answer("Введи корректное время")
        return

    await state.update_data(event_dt=dt.isoformat())
    await state.set_state(WizardStates.waiting_activity)
    await message.answer("Введите активность (1-200 символов):")


@router.message(WizardStates.waiting_date_only)
async def process_date_only(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    tz = ZoneInfo(data["timezone"])
    text = message.text or ""

    result = parse_user_datetime(text, tz)
    if result is None or not result.has_date:
        await message.answer("Не понял дату. Попробуй иначе (например: завтра, 25.12).")
        return

    now = datetime.now(tz)
    dt = result.dt.replace(hour=data["partial_time_h"], minute=data["partial_time_m"], second=0, microsecond=0)

    if dt <= now:
        await message.answer("Введи корректную дату")
        return

    await state.update_data(event_dt=dt.isoformat())
    await state.set_state(WizardStates.waiting_activity)
    await message.answer("Введите активность (1-200 символов):")


@router.message(WizardStates.waiting_activity)
async def process_activity(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text or len(text) > 200:
        await message.answer("Активность должна быть от 1 до 200 символов.")
        return
    await state.update_data(activity=text)
    await state.set_state(WizardStates.waiting_notes)
    await message.answer("Введите заметки (или '-' если без заметок). Перечисление через запятую станет списком:")


@router.message(WizardStates.waiting_notes)
async def process_notes(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    notes = format_notes(text)
    await state.update_data(notes=notes)
    await state.set_state(WizardStates.confirm)
    data = await state.get_data()
    await _show_confirmation(message, data)


async def _show_confirmation(message: Message, data: dict) -> None:
    dt = datetime.fromisoformat(data["event_dt"])
    dt_str = dt.strftime("%d.%m.%Y %H:%M")
    notes_str = data.get("notes") or "—"

    text = (
        f"Подтвердите напоминание:\n\n"
        f"Когда: {dt_str}\n"
        f"Активность: {data['activity']}\n"
        f"Заметки:\n{notes_str}"
    )
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Подтвердить")],
            [KeyboardButton(text="Изменить")],
            [KeyboardButton(text="Отмена")],
        ],
        resize_keyboard=True,
    )
    await message.answer(text, reply_markup=kb)


@router.message(WizardStates.confirm, F.text == "Подтвердить")
async def confirm_event(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    tz = ZoneInfo(data["timezone"])
    dt = datetime.fromisoformat(data["event_dt"])

    event_id = await database.create_event(
        user_id=message.from_user.id,  # type: ignore[union-attr]
        event_dt=dt.isoformat(),
        activity=data["activity"],
        notes=data.get("notes"),
    )

    await schedule_event_jobs(event_id, dt, message.from_user.id)  # type: ignore[union-attr]
    await state.clear()
    await message.answer("Напоминание создано!", reply_markup=MAIN_MENU)


@router.message(WizardStates.confirm, F.text == "Изменить")
async def edit_choice(message: Message, state: FSMContext) -> None:
    await state.set_state(WizardStates.edit_choice)
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Дата/время")],
            [KeyboardButton(text="Активность")],
            [KeyboardButton(text="Заметки")],
            [KeyboardButton(text="Отмена")],
        ],
        resize_keyboard=True,
    )
    await message.answer("Что изменить?", reply_markup=kb)


@router.message(WizardStates.edit_choice, F.text == "Дата/время")
async def edit_date(message: Message, state: FSMContext) -> None:
    await state.set_state(WizardStates.waiting_date)
    await message.answer("Введите новую дату и время:", reply_markup=CANCEL_KB)


@router.message(WizardStates.edit_choice, F.text == "Активность")
async def edit_activity(message: Message, state: FSMContext) -> None:
    await state.set_state(WizardStates.waiting_activity)
    await message.answer("Введите новую активность:", reply_markup=CANCEL_KB)


@router.message(WizardStates.edit_choice, F.text == "Заметки")
async def edit_notes(message: Message, state: FSMContext) -> None:
    await state.set_state(WizardStates.waiting_notes)
    await message.answer("Введите новые заметки:", reply_markup=CANCEL_KB)


@router.message(WizardStates.confirm)
async def confirm_fallback(message: Message, state: FSMContext) -> None:
    await message.answer("Нажмите 'Подтвердить', 'Изменить' или 'Отмена'.")
