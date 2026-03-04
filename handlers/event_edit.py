"""FSM and callbacks for editing already saved events."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, KeyboardButton, Message, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton

import db as database
from notes_fmt import format_notes
from scheduler import cancel_event_jobs, schedule_event_jobs
from .calendar_core import (
    build_date_calendar_kb,
    build_quick_time_kb,
    is_debounced,
    month_shift,
    new_calendar_session_id,
    parse_calendar_callback_with_event,
)
from .duplicates import has_duplicate_event
from .metrics_utils import bump_metric
from .start import MAIN_MENU
from .texts import (
    MSG_ACTIVITY_LEN,
    MSG_CALENDAR_UPDATE_ERROR,
    MSG_CALENDAR_UPDATED,
    MSG_DEBOUNCE,
    MSG_DUPLICATE_WARNING,
    MSG_EDIT_CALENDAR_STEP,
    MSG_EDIT_CANCELLED,
    MSG_EDIT_MENU_FALLBACK,
    MSG_EDIT_TIME_STEP,
    MSG_ENTER_NEW_ACTIVITY,
    MSG_ENTER_NEW_NOTES,
    MSG_ENTER_TIME_MANUAL_EDIT,
    MSG_INVALID_ACTION,
    MSG_INVALID_DATE,
    MSG_PICK_DATE_WITH_BUTTONS,
    MSG_SET_TZ_FIRST,
    MSG_STALE_CALENDAR,
    MSG_TIME_PARSE_ERROR,
    MSG_TIME_PAST,
    MSG_UNAUTHORIZED,
    MSG_UPDATED,
    MSG_WEEK_EDIT_PROMPT,
)

router = Router()


class EditEventStates(StatesGroup):
    edit_menu = State()
    edit_waiting_calendar_date = State()
    edit_waiting_time = State()
    edit_confirm_duplicate = State()
    edit_waiting_activity = State()
    edit_waiting_notes = State()


CANCEL_KB = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="Отмена")]],
    resize_keyboard=True,
)

STEP_EDIT_DATE = MSG_EDIT_CALENDAR_STEP
STEP_EDIT_TIME = MSG_EDIT_TIME_STEP


def parse_evt_callback(data: str) -> tuple[str, int, str | None] | None:
    """Return (action, event_id, field)."""
    parts = data.split(":")

    if len(parts) == 3 and parts[0] == "evt" and parts[1] in {"edit", "cancel"} and parts[2].isdigit():
        return parts[1], int(parts[2]), None

    if (
        len(parts) == 4
        and parts[0] == "evt"
        and parts[1] == "field"
        and parts[2] in {"dt", "activity", "notes"}
        and parts[3].isdigit()
    ):
        return "field", int(parts[3]), parts[2]

    return None


def _with_tz_line(base: str, tz_name: str) -> str:
    return f"{base}\nЧасовой пояс: {tz_name}"


def _calendar_bounds(tz_name: str) -> tuple[date, date]:
    tz = ZoneInfo(tz_name)
    today = datetime.now(tz).date()
    return today, today + timedelta(days=730)


def _quick_date(value: str, today: date) -> date | None:
    if value == "today":
        return today
    if value == "tomorrow":
        return today + timedelta(days=1)
    if value == "plus7":
        return today + timedelta(days=7)
    return None


async def _get_user_tz_name(user_id: int) -> str | None:
    user = await database.get_user(user_id)
    if not user:
        return None
    return user["timezone"]


async def _show_field_menu(message: Message, state: FSMContext, event_id: int, tz_name: str) -> None:
    await state.set_state(EditEventStates.edit_menu)
    await state.update_data(
        edit_event_id=event_id,
        edit_timezone=tz_name,
        edit_selected_date_iso=None,
        edit_dup_sid=None,
        edit_pending_hour=None,
        edit_pending_minute=None,
    )

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Дата/время", callback_data=f"evt:field:dt:{event_id}")],
            [InlineKeyboardButton(text="Активность", callback_data=f"evt:field:activity:{event_id}")],
            [InlineKeyboardButton(text="Заметки", callback_data=f"evt:field:notes:{event_id}")],
            [InlineKeyboardButton(text="Отмена", callback_data=f"evt:cancel:{event_id}")],
        ]
    )
    await message.answer(MSG_WEEK_EDIT_PROMPT, reply_markup=kb)


async def start_edit_menu_for_event(
    message: Message,
    state: FSMContext,
    *,
    user_id: int,
    event_id: int,
) -> tuple[bool, str | None]:
    event = await database.get_active_event_for_user(event_id, user_id)
    if event is None:
        return False, MSG_UNAUTHORIZED

    tz_name = await _get_user_tz_name(user_id)
    if not tz_name:
        return False, MSG_SET_TZ_FIRST

    await _show_field_menu(message, state, event_id, tz_name)
    return True, None


async def _start_edit_calendar_step(
    message: Message,
    state: FSMContext,
    event_id: int,
    tz_name: str,
) -> None:
    today, max_date = _calendar_bounds(tz_name)
    sid = new_calendar_session_id()

    await state.set_state(EditEventStates.edit_waiting_calendar_date)
    await state.update_data(
        edit_event_id=event_id,
        edit_timezone=tz_name,
        edit_cal_session_id=sid,
        edit_cal_view_year=today.year,
        edit_cal_view_month=today.month,
        edit_selected_date_iso=None,
    )

    step_text = _with_tz_line(STEP_EDIT_DATE, tz_name)
    await message.answer(step_text, reply_markup=CANCEL_KB)

    kb = build_date_calendar_kb(
        sid,
        today.year,
        today.month,
        today,
        max_date,
        selected_date=None,
        today_date=today,
        prefix="edtcal2",
        tail_parts=(str(event_id),),
    )

    cal_msg = await message.answer(step_text, reply_markup=kb)
    await state.update_data(edit_cal_message_id=cal_msg.message_id)


def _selected_edit_date_from_data(data: dict) -> date | None:
    selected_iso = data.get("edit_selected_date_iso")
    if not selected_iso:
        return None
    try:
        return date.fromisoformat(selected_iso)
    except ValueError:
        return None


async def _apply_edit_datetime(
    state: FSMContext,
    user_id: int,
    hour: int,
    minute: int,
    *,
    duplicate_override: bool = False,
) -> tuple[bool, str | None]:
    data = await state.get_data()
    event_id = data.get("edit_event_id")
    tz_name = data.get("edit_timezone")
    selected_iso = data.get("edit_selected_date_iso")

    if not event_id or not tz_name or not selected_iso:
        return False, MSG_STALE_CALENDAR

    try:
        selected_date = date.fromisoformat(selected_iso)
    except ValueError:
        return False, MSG_INVALID_DATE

    event = await database.get_active_event_for_user(event_id, user_id)
    if event is None:
        return False, MSG_UNAUTHORIZED

    tz = ZoneInfo(tz_name)
    now = datetime.now(tz)
    new_dt = datetime(
        selected_date.year,
        selected_date.month,
        selected_date.day,
        hour,
        minute,
        tzinfo=tz,
    )

    if new_dt <= now:
        await bump_metric("time_past_reject")
        return False, MSG_TIME_PAST

    if not duplicate_override:
        duplicate = await has_duplicate_event(
            user_id=user_id,
            event_dt_iso=new_dt.isoformat(),
            activity=event["activity"],
            exclude_event_id=event_id,
        )
        if duplicate:
            dup_sid = new_calendar_session_id()
            await state.set_state(EditEventStates.edit_confirm_duplicate)
            await state.update_data(
                edit_dup_sid=dup_sid,
                edit_pending_hour=hour,
                edit_pending_minute=minute,
            )
            return False, "DUPLICATE"

    await database.update_event_datetime(event_id, new_dt.isoformat())
    await cancel_event_jobs(event_id)
    await schedule_event_jobs(event_id, new_dt, user_id)
    await bump_metric("edit_success")
    await state.clear()
    return True, None


@router.message(EditEventStates.edit_menu, F.text == "Отмена")
@router.message(EditEventStates.edit_waiting_calendar_date, F.text == "Отмена")
@router.message(EditEventStates.edit_waiting_time, F.text == "Отмена")
@router.message(EditEventStates.edit_confirm_duplicate, F.text == "Отмена")
@router.message(EditEventStates.edit_waiting_activity, F.text == "Отмена")
@router.message(EditEventStates.edit_waiting_notes, F.text == "Отмена")
async def cancel_edit_by_text(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(MSG_EDIT_CANCELLED, reply_markup=MAIN_MENU)


@router.callback_query(F.data.startswith("evt:"))
async def on_evt_callback(callback: CallbackQuery, state: FSMContext) -> None:
    user_id = callback.from_user.id  # type: ignore[union-attr]
    if is_debounced(user_id):
        await bump_metric("callback_debounce_reject")
        await callback.answer(MSG_DEBOUNCE)
        return

    parsed = parse_evt_callback(callback.data or "")
    if parsed is None:
        await bump_metric("callback_invalid_payload")
        await callback.answer(MSG_INVALID_ACTION)
        return

    action, event_id, field = parsed

    if action == "edit":
        if callback.message is None:
            await callback.answer(MSG_INVALID_ACTION)
            return
        ok, error = await start_edit_menu_for_event(
            callback.message,
            state,
            user_id=user_id,
            event_id=event_id,
        )
        await callback.answer()
        if not ok and error:
            await callback.message.answer(error)
        return

    if action == "cancel":
        await state.clear()
        await callback.answer()
        if callback.message:
            await callback.message.answer(MSG_EDIT_CANCELLED, reply_markup=MAIN_MENU)
        return

    if action == "field" and field == "dt":
        event = await database.get_active_event_for_user(event_id, user_id)
        if event is None:
            await bump_metric("ownership_reject")
            await callback.answer(MSG_UNAUTHORIZED)
            return

        tz_name = await _get_user_tz_name(user_id)
        if not tz_name:
            await callback.answer(MSG_SET_TZ_FIRST)
            return

        await callback.answer()
        if callback.message:
            await _start_edit_calendar_step(callback.message, state, event_id, tz_name)
        return

    if action == "field" and field == "activity":
        event = await database.get_active_event_for_user(event_id, user_id)
        if event is None:
            await bump_metric("ownership_reject")
            await callback.answer(MSG_UNAUTHORIZED)
            return

        tz_name = await _get_user_tz_name(user_id)
        if not tz_name:
            await callback.answer(MSG_SET_TZ_FIRST)
            return

        await state.set_state(EditEventStates.edit_waiting_activity)
        await state.update_data(edit_event_id=event_id, edit_timezone=tz_name)
        await callback.answer()
        if callback.message:
            await callback.message.answer(MSG_ENTER_NEW_ACTIVITY, reply_markup=CANCEL_KB)
        return

    if action == "field" and field == "notes":
        event = await database.get_active_event_for_user(event_id, user_id)
        if event is None:
            await bump_metric("ownership_reject")
            await callback.answer(MSG_UNAUTHORIZED)
            return

        tz_name = await _get_user_tz_name(user_id)
        if not tz_name:
            await callback.answer(MSG_SET_TZ_FIRST)
            return

        await state.set_state(EditEventStates.edit_waiting_notes)
        await state.update_data(edit_event_id=event_id, edit_timezone=tz_name)
        await callback.answer()
        if callback.message:
            await callback.message.answer(MSG_ENTER_NEW_NOTES, reply_markup=CANCEL_KB)
        return

    await callback.answer(MSG_INVALID_ACTION)


@router.callback_query(EditEventStates.edit_waiting_calendar_date, F.data.startswith("edtcal2:"))
async def on_edit_calendar_date(callback: CallbackQuery, state: FSMContext) -> None:
    user_id = callback.from_user.id  # type: ignore[union-attr]
    if is_debounced(user_id):
        await bump_metric("callback_debounce_reject")
        await callback.answer(MSG_DEBOUNCE)
        return

    payload = parse_calendar_callback_with_event(callback.data or "", prefix="edtcal2")
    if payload is None:
        await bump_metric("callback_invalid_payload")
        await callback.answer(MSG_INVALID_ACTION)
        return

    kind, parsed = payload
    data = await state.get_data()

    expected_sid = data.get("edit_cal_session_id")
    expected_event_id = data.get("edit_event_id")
    tz_name = data.get("edit_timezone")

    if not expected_sid or not expected_event_id or not tz_name:
        await bump_metric("callback_stale_session")
        await callback.answer(MSG_STALE_CALENDAR)
        return

    if parsed["sid"] != expected_sid or parsed["event_id"] != expected_event_id:
        await bump_metric("callback_stale_session")
        await callback.answer(MSG_STALE_CALENDAR)
        return

    event = await database.get_active_event_for_user(expected_event_id, user_id)
    if event is None:
        await bump_metric("ownership_reject")
        await callback.answer(MSG_UNAUTHORIZED)
        return

    if kind == "noop":
        await callback.answer()
        return

    if kind == "cancel":
        await state.clear()
        await callback.answer()
        if callback.message:
            await callback.message.answer(MSG_EDIT_CANCELLED, reply_markup=MAIN_MENU)
        return

    if callback.message is None:
        await callback.answer(MSG_INVALID_ACTION)
        return

    today, max_date = _calendar_bounds(tz_name)

    if kind == "nav":
        if callback.message.message_id != data.get("edit_cal_message_id"):
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
            selected_date=_selected_edit_date_from_data(data),
            today_date=today,
            prefix="edtcal2",
            tail_parts=(str(expected_event_id),),
        )
        text = _with_tz_line(STEP_EDIT_DATE, tz_name)

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
                    edit_cal_message_id=new_msg.message_id,
                    edit_cal_view_year=new_year,
                    edit_cal_view_month=new_month,
                )
                await callback.answer(MSG_CALENDAR_UPDATED)
                return
            await callback.answer(MSG_CALENDAR_UPDATE_ERROR)
            return

        await state.update_data(edit_cal_view_year=new_year, edit_cal_view_month=new_month)
        await callback.answer()
        return

    if kind in {"day", "quick"}:
        if kind == "day":
            selected = parsed["date"]
        else:
            quick = _quick_date(parsed["value"], today)
            if quick is None:
                await callback.answer(MSG_INVALID_ACTION)
                return
            selected = quick

        if selected < today or selected > max_date:
            await callback.answer(MSG_INVALID_DATE)
            return

        await state.update_data(edit_selected_date_iso=selected.isoformat())
        await state.set_state(EditEventStates.edit_waiting_time)

        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except TelegramBadRequest:
            pass

        await callback.answer()
        await callback.message.answer(
            _with_tz_line(STEP_EDIT_TIME, tz_name),
            reply_markup=build_quick_time_kb(
                expected_sid,
                prefix="edtcal2",
                tail_parts=(str(expected_event_id),),
            ),
        )
        return

    await callback.answer(MSG_INVALID_ACTION)


@router.callback_query(EditEventStates.edit_waiting_time, F.data.startswith("edtcal2:"))
async def on_edit_time_callback(callback: CallbackQuery, state: FSMContext) -> None:
    user_id = callback.from_user.id  # type: ignore[union-attr]
    if is_debounced(user_id):
        await bump_metric("callback_debounce_reject")
        await callback.answer(MSG_DEBOUNCE)
        return

    payload = parse_calendar_callback_with_event(callback.data or "", prefix="edtcal2")
    if payload is None:
        await bump_metric("callback_invalid_payload")
        await callback.answer(MSG_INVALID_ACTION)
        return

    kind, parsed = payload
    data = await state.get_data()

    expected_sid = data.get("edit_cal_session_id")
    expected_event_id = data.get("edit_event_id")

    if not expected_sid or not expected_event_id:
        await bump_metric("callback_stale_session")
        await callback.answer(MSG_STALE_CALENDAR)
        return

    if parsed["sid"] != expected_sid or parsed["event_id"] != expected_event_id:
        await bump_metric("callback_stale_session")
        await callback.answer(MSG_STALE_CALENDAR)
        return

    event = await database.get_active_event_for_user(expected_event_id, user_id)
    if event is None:
        await bump_metric("ownership_reject")
        await callback.answer(MSG_UNAUTHORIZED)
        return

    if kind == "noop":
        await callback.answer()
        return

    if kind == "cancel":
        await state.clear()
        await callback.answer()
        if callback.message:
            await callback.message.answer(MSG_EDIT_CANCELLED, reply_markup=MAIN_MENU)
        return

    if kind != "time":
        await callback.answer(MSG_INVALID_ACTION)
        return

    if parsed["value"] == "manual":
        await callback.answer()
        if callback.message:
            await callback.message.answer(MSG_ENTER_TIME_MANUAL_EDIT)
        return

    hhmm = parsed["value"]
    hour = int(hhmm[:2])
    minute = int(hhmm[2:])

    ok, error = await _apply_edit_datetime(state, user_id, hour, minute)
    if not ok:
        await callback.answer()
        if callback.message:
            if error == "DUPLICATE":
                data = await state.get_data()
                await bump_metric("duplicate_warning_shown")
                await callback.message.answer(
                    MSG_DUPLICATE_WARNING,
                    reply_markup=_duplicate_warning_kb(data["edit_dup_sid"]),
                )
                return
            await callback.message.answer(error or MSG_INVALID_ACTION)
        return

    await callback.answer()
    if callback.message:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except TelegramBadRequest:
            pass
        await callback.message.answer(MSG_UPDATED, reply_markup=MAIN_MENU)


@router.message(EditEventStates.edit_waiting_calendar_date)
async def waiting_edit_calendar_date_text_fallback(message: Message) -> None:
    await message.answer(MSG_PICK_DATE_WITH_BUTTONS)


@router.message(EditEventStates.edit_waiting_time)
async def process_edit_time_manual(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip().lower()

    from date_parser import _parse_time_str

    data = await state.get_data()
    tz_name = data.get("edit_timezone")
    if not tz_name:
        await message.answer(MSG_STALE_CALENDAR)
        return

    tz = ZoneInfo(tz_name)
    now = datetime.now(tz)
    parsed_time = _parse_time_str(text, now, tz)
    if parsed_time is None:
        await bump_metric("time_parse_error")
        await message.answer(MSG_TIME_PARSE_ERROR)
        return

    ok, error = await _apply_edit_datetime(state, message.from_user.id, parsed_time[0], parsed_time[1])  # type: ignore[union-attr]
    if not ok:
        if error == "DUPLICATE":
            data = await state.get_data()
            await bump_metric("duplicate_warning_shown")
            await message.answer(
                MSG_DUPLICATE_WARNING,
                reply_markup=_duplicate_warning_kb(data["edit_dup_sid"]),
            )
            return
        await message.answer(error or MSG_INVALID_ACTION)
        return

    await message.answer(MSG_UPDATED, reply_markup=MAIN_MENU)


def _duplicate_warning_kb(sid: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Сохранить", callback_data=f"dup2:{sid}:save")],
            [InlineKeyboardButton(text="Отмена", callback_data=f"dup2:{sid}:cancel")],
        ]
    )


def _parse_duplicate_callback(data: str) -> tuple[str, str] | None:
    parts = data.split(":")
    if len(parts) != 3 or parts[0] != "dup2" or parts[2] not in {"save", "cancel"}:
        return None
    return parts[1], parts[2]


@router.callback_query(EditEventStates.edit_confirm_duplicate, F.data.startswith("dup2:"))
async def on_edit_duplicate_decision(callback: CallbackQuery, state: FSMContext) -> None:
    parsed = _parse_duplicate_callback(callback.data or "")
    if parsed is None:
        await bump_metric("callback_invalid_payload")
        await callback.answer(MSG_INVALID_ACTION)
        return

    sid, action = parsed
    data = await state.get_data()
    expected_sid = data.get("edit_dup_sid")
    event_id = data.get("edit_event_id")
    tz_name = data.get("edit_timezone")

    if not expected_sid or sid != expected_sid:
        await bump_metric("callback_stale_session")
        await callback.answer(MSG_STALE_CALENDAR)
        return

    if action == "cancel":
        await callback.answer()
        if callback.message and event_id and tz_name:
            await _show_field_menu(callback.message, state, event_id, tz_name)
        return

    pending_hour = data.get("edit_pending_hour")
    pending_minute = data.get("edit_pending_minute")
    if pending_hour is None or pending_minute is None:
        await callback.answer(MSG_INVALID_ACTION)
        return

    ok, error = await _apply_edit_datetime(
        state,
        callback.from_user.id,  # type: ignore[union-attr]
        int(pending_hour),
        int(pending_minute),
        duplicate_override=True,
    )
    if not ok:
        await callback.answer(error or MSG_INVALID_ACTION)
        return

    await callback.answer()
    await bump_metric("duplicate_override_save")
    if callback.message:
        await callback.message.answer(MSG_UPDATED, reply_markup=MAIN_MENU)


@router.message(EditEventStates.edit_waiting_activity)
async def process_edit_activity(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text or len(text) > 200:
        await message.answer(MSG_ACTIVITY_LEN)
        return

    user_id = message.from_user.id  # type: ignore[union-attr]
    data = await state.get_data()
    event_id = data.get("edit_event_id")
    if not event_id:
        await message.answer(MSG_INVALID_ACTION)
        return

    event = await database.get_active_event_for_user(event_id, user_id)
    if event is None:
        await bump_metric("ownership_reject")
        await message.answer(MSG_UNAUTHORIZED)
        await state.clear()
        return

    await database.update_event_activity(event_id, text)
    await bump_metric("edit_success")
    await state.clear()
    await message.answer(MSG_UPDATED, reply_markup=MAIN_MENU)


@router.message(EditEventStates.edit_waiting_notes)
async def process_edit_notes(message: Message, state: FSMContext) -> None:
    user_id = message.from_user.id  # type: ignore[union-attr]
    data = await state.get_data()
    event_id = data.get("edit_event_id")
    if not event_id:
        await message.answer(MSG_INVALID_ACTION)
        return

    event = await database.get_active_event_for_user(event_id, user_id)
    if event is None:
        await bump_metric("ownership_reject")
        await message.answer(MSG_UNAUTHORIZED)
        await state.clear()
        return

    notes = format_notes((message.text or "").strip())
    await database.update_event_notes(event_id, notes)
    await bump_metric("edit_success")
    await state.clear()
    await message.answer(MSG_UPDATED, reply_markup=MAIN_MENU)


@router.message(EditEventStates.edit_menu)
async def edit_menu_fallback(message: Message) -> None:
    await message.answer(MSG_EDIT_MENU_FALLBACK)
