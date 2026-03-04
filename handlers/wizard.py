"""Wizard FSM for creating a new reminder."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, KeyboardButton, Message, ReplyKeyboardMarkup

import db as database
from scheduler import schedule_event_jobs
from .calendar_core import (
    build_date_calendar_kb,
    build_quick_time_kb,
    is_debounced,
    month_shift,
    new_calendar_session_id,
    parse_calendar_callback,
)
from .duplicates import has_duplicate_event
from .flow_common import (
    build_duplicate_warning_kb,
    calendar_bounds,
    parse_duplicate_callback,
    quick_date,
)
from .metrics_utils import bump_metric
from .start import MAIN_MENU
from .time_picker import (
    apply_picker_action,
    build_time_picker_kb,
    parse_time_picker_callback,
    picker_initial_now,
)
from .ui_common import format_step_with_tz, format_time_picker_text
from .texts import (
    MSG_ACTIVITY_LEN,
    MSG_CALENDAR_STEP,
    MSG_CALENDAR_UPDATE_ERROR,
    MSG_CALENDAR_UPDATED,
    MSG_CONFIRM_FALLBACK,
    MSG_CREATION_CANCELLED,
    MSG_DEBOUNCE,
    MSG_DUPLICATE_WARNING,
    MSG_EDIT_CALENDAR_STEP,
    MSG_ENTER_ACTIVITY,
    MSG_ENTER_NEW_ACTIVITY,
    MSG_INVALID_ACTION,
    MSG_INVALID_DATE,
    MSG_PICK_DATE_WITH_BUTTONS,
    MSG_PICK_TIME_WITH_BUTTONS,
    MSG_SET_TZ_FIRST,
    MSG_STALE_CALENDAR,
    MSG_TIME_PAST,
    MSG_TIME_STEP,
    MSG_WHAT_TO_EDIT,
    format_event_preview,
    format_saved_summary,
)

router = Router()


class WizardStates(StatesGroup):
    waiting_calendar_date = State()
    waiting_time_after_calendar = State()
    waiting_activity = State()
    confirm = State()
    edit_choice = State()


CANCEL_KB = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="Отмена")]],
    resize_keyboard=True,
)

STEP_DATE = MSG_CALENDAR_STEP
STEP_TIME = MSG_TIME_STEP


def _selected_date_from_data(data: dict) -> date | None:
    selected_iso = data.get("selected_date_iso")
    if not selected_iso:
        return None
    try:
        return date.fromisoformat(selected_iso)
    except ValueError:
        return None


def _time_picker_text(tz_name: str, hour: int, minute: int) -> str:
    return format_time_picker_text(STEP_TIME, tz_name, hour, minute)


async def _open_create_time_picker(
    message: Message,
    state: FSMContext,
    *,
    tz_name: str,
) -> None:
    sid = new_calendar_session_id()
    hour, minute = picker_initial_now(tz_name)
    await state.update_data(
        tp_sid=sid,
        tp_hour=hour,
        tp_minute=minute,
    )
    sent = await message.answer(
        _time_picker_text(tz_name, hour, minute),
        reply_markup=build_time_picker_kb(sid, hour, minute),
    )
    await state.update_data(tp_message_id=sent.message_id)


async def _start_calendar_step(message: Message, state: FSMContext, tz_name: str) -> None:
    today, max_date = calendar_bounds(tz_name)
    sid = new_calendar_session_id()

    await state.set_state(WizardStates.waiting_calendar_date)
    await state.update_data(
        timezone=tz_name,
        cal_session_id=sid,
        cal_view_year=today.year,
        cal_view_month=today.month,
        selected_date_iso=None,
    )

    step_text = format_step_with_tz(STEP_DATE, tz_name)
    await message.answer(step_text, reply_markup=CANCEL_KB)
    kb = build_date_calendar_kb(
        sid,
        today.year,
        today.month,
        today,
        max_date,
        selected_date=None,
        today_date=today,
        prefix="cal2",
    )
    cal_msg = await message.answer(step_text, reply_markup=kb)
    await state.update_data(cal_message_id=cal_msg.message_id)


async def _apply_selected_time(
    state: FSMContext,
    tz_name: str,
    hour: int,
    minute: int,
) -> tuple[bool, str | None]:
    data = await state.get_data()
    selected_iso = data.get("selected_date_iso")
    if not selected_iso:
        return False, MSG_STALE_CALENDAR

    try:
        selected_date = date.fromisoformat(selected_iso)
    except ValueError:
        return False, MSG_INVALID_DATE

    tz = ZoneInfo(tz_name)
    now = datetime.now(tz)
    dt = datetime(
        selected_date.year,
        selected_date.month,
        selected_date.day,
        hour,
        minute,
        tzinfo=tz,
    )

    if dt <= now:
        await bump_metric("time_past_reject")
        return False, MSG_TIME_PAST

    await state.update_data(event_dt=dt.isoformat())
    await state.set_state(WizardStates.waiting_activity)
    return True, None


@router.message(F.text == "Напомнить")
async def start_wizard(message: Message, state: FSMContext) -> None:
    user_id = message.from_user.id  # type: ignore[union-attr]
    user = await database.get_user(user_id)
    if not user:
        await message.answer(MSG_SET_TZ_FIRST)
        return

    await state.clear()
    await state.update_data(timezone=user["timezone"])
    await _start_calendar_step(message, state, user["timezone"])


@router.message(WizardStates.waiting_calendar_date, F.text == "Отмена")
@router.message(WizardStates.waiting_time_after_calendar, F.text == "Отмена")
@router.message(WizardStates.waiting_activity, F.text == "Отмена")
@router.message(WizardStates.confirm, F.text == "Отмена")
@router.message(WizardStates.edit_choice, F.text == "Отмена")
async def cancel_wizard(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(MSG_CREATION_CANCELLED, reply_markup=MAIN_MENU)


@router.callback_query(WizardStates.waiting_calendar_date, F.data.startswith("cal2:"))
async def on_calendar_date(callback: CallbackQuery, state: FSMContext) -> None:
    user_id = callback.from_user.id  # type: ignore[union-attr]
    if is_debounced(user_id):
        await bump_metric("callback_debounce_reject")
        await callback.answer(MSG_DEBOUNCE)
        return

    payload = parse_calendar_callback(callback.data or "", prefix="cal2")
    if payload is None:
        await bump_metric("callback_invalid_payload")
        await callback.answer(MSG_INVALID_ACTION)
        return

    kind, parsed = payload
    data = await state.get_data()
    expected_sid = data.get("cal_session_id")
    tz_name = data.get("timezone")

    if not expected_sid or not tz_name:
        await bump_metric("callback_stale_session")
        await callback.answer(MSG_STALE_CALENDAR)
        return

    if parsed.get("sid") != expected_sid:
        await bump_metric("callback_stale_session")
        await callback.answer(MSG_STALE_CALENDAR)
        return

    if kind == "noop":
        await callback.answer()
        return

    if kind == "cancel":
        await state.clear()
        await callback.answer()
        if callback.message:
            await callback.message.answer(MSG_CREATION_CANCELLED, reply_markup=MAIN_MENU)
        return

    if callback.message is None:
        await callback.answer(MSG_INVALID_ACTION)
        return

    today, max_date = calendar_bounds(tz_name)

    if kind == "nav":
        if callback.message.message_id != data.get("cal_message_id"):
            await bump_metric("callback_stale_session")
            await callback.answer(MSG_STALE_CALENDAR)
            return

        shift = -1 if parsed["direction"] == "prev" else 1
        new_year, new_month = month_shift(parsed["year"], parsed["month"], shift)

        min_month = (today.year, today.month)
        max_month = (max_date.year, max_date.month)
        if (new_year, new_month) < min_month:
            new_year, new_month = min_month
        if (new_year, new_month) > max_month:
            new_year, new_month = max_month

        kb = build_date_calendar_kb(
            expected_sid,
            new_year,
            new_month,
            today,
            max_date,
            selected_date=_selected_date_from_data(data),
            today_date=today,
            prefix="cal2",
        )
        text = format_step_with_tz(STEP_DATE, tz_name)

        try:
            await callback.message.edit_text(text, reply_markup=kb)
        except TelegramBadRequest as exc:
            lowered = str(exc).lower()
            if "message is not modified" in lowered:
                await callback.answer()
                return
            if "message to edit not found" in lowered:
                new_msg = await callback.message.answer(text, reply_markup=kb)
                await state.update_data(
                    cal_message_id=new_msg.message_id,
                    cal_view_year=new_year,
                    cal_view_month=new_month,
                )
                await callback.answer(MSG_CALENDAR_UPDATED)
                return
            await callback.answer(MSG_CALENDAR_UPDATE_ERROR)
            return

        await state.update_data(cal_view_year=new_year, cal_view_month=new_month)
        await callback.answer()
        return

    if kind in {"day", "quick"}:
        if kind == "day":
            selected = parsed["date"]
        else:
            quick = quick_date(parsed["value"], today)
            if quick is None:
                await callback.answer(MSG_INVALID_ACTION)
                return
            selected = quick

        if selected < today or selected > max_date:
            await callback.answer(MSG_INVALID_DATE)
            return

        await state.update_data(selected_date_iso=selected.isoformat())
        await state.set_state(WizardStates.waiting_time_after_calendar)

        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except TelegramBadRequest:
            pass

        await callback.answer()
        await callback.message.answer(
            format_step_with_tz(STEP_TIME, tz_name),
            reply_markup=build_quick_time_kb(expected_sid, prefix="cal2"),
        )
        return

    await callback.answer(MSG_INVALID_ACTION)


@router.callback_query(WizardStates.waiting_time_after_calendar, F.data.startswith("cal2:"))
async def on_quick_time(callback: CallbackQuery, state: FSMContext) -> None:
    user_id = callback.from_user.id  # type: ignore[union-attr]
    if is_debounced(user_id):
        await bump_metric("callback_debounce_reject")
        await callback.answer(MSG_DEBOUNCE)
        return

    payload = parse_calendar_callback(callback.data or "", prefix="cal2")
    if payload is None:
        await bump_metric("callback_invalid_payload")
        await callback.answer(MSG_INVALID_ACTION)
        return

    kind, parsed = payload
    data = await state.get_data()
    expected_sid = data.get("cal_session_id")
    tz_name = data.get("timezone")

    if not expected_sid or not tz_name:
        await bump_metric("callback_stale_session")
        await callback.answer(MSG_STALE_CALENDAR)
        return

    if parsed.get("sid") != expected_sid:
        await bump_metric("callback_stale_session")
        await callback.answer(MSG_STALE_CALENDAR)
        return

    if kind == "noop":
        await callback.answer()
        return

    if kind == "cancel":
        await state.clear()
        await callback.answer()
        if callback.message:
            await callback.message.answer(MSG_CREATION_CANCELLED, reply_markup=MAIN_MENU)
        return

    if kind != "time":
        await callback.answer(MSG_INVALID_ACTION)
        return

    if parsed["value"] == "picker":
        if not data.get("selected_date_iso"):
            await bump_metric("callback_stale_session")
            await callback.answer(MSG_STALE_CALENDAR)
            if callback.message:
                await callback.message.answer(MSG_PICK_DATE_WITH_BUTTONS)
            return
        await callback.answer()
        if callback.message:
            await _open_create_time_picker(callback.message, state, tz_name=tz_name)
        return

    hhmm = parsed["value"]
    hour = int(hhmm[:2])
    minute = int(hhmm[2:])

    ok, error = await _apply_selected_time(state, tz_name, hour, minute)
    if not ok:
        await callback.answer()
        if callback.message:
            await callback.message.answer(error or MSG_INVALID_ACTION)
        return

    await callback.answer()
    if callback.message:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except TelegramBadRequest:
            pass
        await callback.message.answer(MSG_ENTER_ACTIVITY)


@router.callback_query(WizardStates.waiting_time_after_calendar, F.data.startswith("tmr2:"))
async def on_create_time_picker(callback: CallbackQuery, state: FSMContext) -> None:
    user_id = callback.from_user.id  # type: ignore[union-attr]
    if is_debounced(user_id):
        await bump_metric("callback_debounce_reject")
        await callback.answer(MSG_DEBOUNCE)
        return

    payload = parse_time_picker_callback(callback.data or "")
    if payload is None:
        await bump_metric("callback_invalid_payload")
        await callback.answer(MSG_INVALID_ACTION)
        return

    kind, parsed = payload
    data = await state.get_data()
    expected_sid = data.get("tp_sid")
    tz_name = data.get("timezone")

    if not expected_sid or not tz_name:
        await bump_metric("callback_stale_session")
        await callback.answer(MSG_STALE_CALENDAR)
        return

    if parsed.get("sid") != expected_sid:
        await bump_metric("callback_stale_session")
        await callback.answer(MSG_STALE_CALENDAR)
        return

    if callback.message is None:
        await bump_metric("callback_invalid_payload")
        await callback.answer(MSG_INVALID_ACTION)
        return

    if kind == "noop":
        await callback.answer()
        return

    if kind == "cancel":
        await state.update_data(tp_sid=None, tp_message_id=None)
        await callback.answer()
        cal_sid = data.get("cal_session_id")
        if not cal_sid:
            await bump_metric("callback_stale_session")
            await callback.message.answer(MSG_STALE_CALENDAR)
            return
        await callback.message.answer(
            format_step_with_tz(STEP_TIME, tz_name),
            reply_markup=build_quick_time_kb(cal_sid, prefix="cal2"),
        )
        return

    if kind == "ok":
        hour = int(data.get("tp_hour", 0))
        minute = int(data.get("tp_minute", 0))
        ok, error = await _apply_selected_time(state, tz_name, hour, minute)
        if not ok:
            await callback.answer()
            await callback.message.answer(error or MSG_INVALID_ACTION)
            return
        await callback.answer()
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except TelegramBadRequest:
            pass
        await callback.message.answer(MSG_ENTER_ACTIVITY)
        return

    hour = int(data.get("tp_hour", 0))
    minute = int(data.get("tp_minute", 0))
    hour, minute = apply_picker_action(
        hour,
        minute,
        kind,
        parsed.get("value"),
        tz_name=tz_name,
    )

    await state.update_data(tp_hour=hour, tp_minute=minute)
    try:
        await callback.message.edit_text(
            _time_picker_text(tz_name, hour, minute),
            reply_markup=build_time_picker_kb(expected_sid, hour, minute),
        )
    except TelegramBadRequest:
        pass
    await callback.answer()


@router.message(WizardStates.waiting_calendar_date)
async def waiting_calendar_date_text_fallback(message: Message) -> None:
    await message.answer(MSG_PICK_DATE_WITH_BUTTONS)


@router.message(WizardStates.waiting_time_after_calendar)
async def process_time_after_calendar(message: Message, state: FSMContext) -> None:
    await message.answer(MSG_PICK_TIME_WITH_BUTTONS)


@router.message(WizardStates.waiting_activity)
async def process_activity(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text or len(text) > 200:
        await message.answer(MSG_ACTIVITY_LEN)
        return
    await state.update_data(activity=text)
    await state.set_state(WizardStates.confirm)
    await state.update_data(create_dup_sid=None)
    data = await state.get_data()
    await _show_confirmation(message, data)


async def _show_confirmation(message: Message, data: dict) -> None:
    dt = datetime.fromisoformat(data["event_dt"])
    text = format_event_preview(
        dt=dt,
        activity=data["activity"],
        mode="create",
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
    user_id = message.from_user.id  # type: ignore[union-attr]
    data_before = await state.get_data()
    ok, error = await _finalize_create(state, user_id=user_id, duplicate_override=False)
    if not ok and error == "DUPLICATE":
        data = await state.get_data()
        await bump_metric("duplicate_warning_shown")
        await message.answer(
            MSG_DUPLICATE_WARNING,
            reply_markup=build_duplicate_warning_kb(data["create_dup_sid"]),
        )
        return

    if not ok:
        await message.answer(error or MSG_INVALID_ACTION)
        return

    summary = format_saved_summary(
        dt=datetime.fromisoformat(data_before["event_dt"]),
        activity=data_before["activity"],
    )
    await message.answer(summary, reply_markup=MAIN_MENU)


async def _finalize_create(
    state: FSMContext,
    *,
    user_id: int,
    duplicate_override: bool,
) -> tuple[bool, str | None]:
    data = await state.get_data()
    dt_iso = data.get("event_dt")
    activity = data.get("activity")
    if not dt_iso or not activity:
        return False, MSG_INVALID_ACTION

    if not duplicate_override:
        duplicate = await has_duplicate_event(
            user_id=user_id,
            event_dt_iso=dt_iso,
            activity=activity,
        )
        if duplicate:
            dup_sid = new_calendar_session_id()
            await state.update_data(create_dup_sid=dup_sid)
            return False, "DUPLICATE"

    dt = datetime.fromisoformat(dt_iso)
    event_id = await database.create_event(
        user_id=user_id,
        event_dt=dt.isoformat(),
        activity=activity,
        notes=None,
    )
    await schedule_event_jobs(event_id, dt, user_id)
    await bump_metric("create_success")
    await state.clear()
    return True, None


@router.callback_query(WizardStates.confirm, F.data.startswith("dup2:"))
async def on_create_duplicate_decision(callback: CallbackQuery, state: FSMContext) -> None:
    parsed = parse_duplicate_callback(callback.data or "")
    if parsed is None:
        await bump_metric("callback_invalid_payload")
        await callback.answer(MSG_INVALID_ACTION)
        return

    sid, action = parsed
    data = await state.get_data()
    expected_sid = data.get("create_dup_sid")
    if not expected_sid or sid != expected_sid:
        await bump_metric("callback_stale_session")
        await callback.answer(MSG_STALE_CALENDAR)
        return

    if action == "cancel":
        await state.update_data(create_dup_sid=None)
        await callback.answer()
        if callback.message:
            data = await state.get_data()
            await _show_confirmation(callback.message, data)
        return

    data_before = await state.get_data()
    ok, error = await _finalize_create(
        state,
        user_id=callback.from_user.id,  # type: ignore[union-attr]
        duplicate_override=True,
    )
    if not ok:
        await callback.answer(error or MSG_INVALID_ACTION)
        return

    await bump_metric("duplicate_override_save")
    await callback.answer()
    if callback.message:
        summary = format_saved_summary(
            dt=datetime.fromisoformat(data_before["event_dt"]),
            activity=data_before["activity"],
        )
        await callback.message.answer(summary, reply_markup=MAIN_MENU)


@router.message(WizardStates.confirm, F.text == "Изменить")
async def edit_choice(message: Message, state: FSMContext) -> None:
    await state.set_state(WizardStates.edit_choice)
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Дата/время")],
            [KeyboardButton(text="Активность")],
            [KeyboardButton(text="Отмена")],
        ],
        resize_keyboard=True,
    )
    await message.answer(MSG_WHAT_TO_EDIT, reply_markup=kb)


@router.message(WizardStates.edit_choice, F.text == "Дата/время")
async def edit_date(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    tz_name = data.get("timezone")
    if not tz_name:
        user = await database.get_user(message.from_user.id)  # type: ignore[union-attr]
        if not user:
            await message.answer(MSG_SET_TZ_FIRST)
            return
        tz_name = user["timezone"]
        await state.update_data(timezone=tz_name)

    await _start_calendar_step(message, state, tz_name)


@router.message(WizardStates.edit_choice, F.text == "Активность")
async def edit_activity(message: Message, state: FSMContext) -> None:
    await state.set_state(WizardStates.waiting_activity)
    await message.answer(MSG_ENTER_NEW_ACTIVITY, reply_markup=CANCEL_KB)


@router.message(WizardStates.confirm)
async def confirm_fallback(message: Message, state: FSMContext) -> None:
    await message.answer(MSG_CONFIRM_FALLBACK)
