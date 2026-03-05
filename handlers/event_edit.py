"""FSM and callbacks for editing already saved events."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, KeyboardButton, Message, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton

import db as database
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
from .flow_common import (
    build_duplicate_warning_kb,
    calendar_bounds,
    clamp_month_to_bounds,
    parse_duplicate_callback,
    quick_date,
    state_iso_date,
)
from .input_hints import reply_pick_date_hint, reply_pick_time_hint
from .metrics_utils import bump_metric
from .picker_flow import apply_picker_delta_and_render, resolve_picker_context
from .start import MAIN_MENU
from .task_browser import return_to_browser_context
from .time_picker import (
    build_time_picker_kb,
    picker_initial_now,
)
from .ui_common import format_step_with_tz, format_time_picker_text
from .ui_tokens import CANCEL_TEXT, STYLE_DANGER
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
    MSG_INVALID_ACTION,
    MSG_INVALID_DATE,
    MSG_PICK_DATE_WITH_BUTTONS,
    MSG_SET_TZ_FIRST,
    MSG_STALE_CALENDAR,
    MSG_TIME_PAST,
    MSG_UNAUTHORIZED,
    MSG_WEEK_EDIT_PROMPT,
    format_saved_summary,
)

router = Router()


class EditEventStates(StatesGroup):
    edit_menu = State()
    edit_waiting_calendar_date = State()
    edit_waiting_time = State()
    edit_confirm_duplicate = State()
    edit_waiting_activity = State()


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
        and parts[2] in {"dt", "activity"}
        and parts[3].isdigit()
    ):
        return "field", int(parts[3]), parts[2]

    return None


def _time_picker_text(tz_name: str, hour: int, minute: int) -> str:
    return format_time_picker_text(STEP_EDIT_TIME, tz_name, hour, minute)


async def _open_edit_time_picker(
    message: Message,
    state: FSMContext,
    *,
    tz_name: str,
) -> None:
    sid = new_calendar_session_id()
    hour, minute = picker_initial_now(tz_name)
    await state.update_data(
        edit_tp_sid=sid,
        edit_tp_hour=hour,
        edit_tp_minute=minute,
    )
    sent = await message.answer(
        _time_picker_text(tz_name, hour, minute),
        reply_markup=build_time_picker_kb(sid, hour, minute),
    )
    await state.update_data(edit_tp_message_id=sent.message_id)


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
            [InlineKeyboardButton(text=CANCEL_TEXT, callback_data=f"evt:cancel:{event_id}", style=STYLE_DANGER)],
        ]
    )
    await message.answer(MSG_WEEK_EDIT_PROMPT, reply_markup=kb)


async def start_edit_menu_for_event(
    message: Message,
    state: FSMContext,
    *,
    user_id: int,
    event_id: int,
    return_to_browser: bool = False,
) -> tuple[bool, str | None]:
    event = await database.get_active_event_for_user(event_id, user_id)
    if event is None:
        return False, MSG_UNAUTHORIZED

    tz_name = await _get_user_tz_name(user_id)
    if not tz_name:
        return False, MSG_SET_TZ_FIRST

    await _show_field_menu(message, state, event_id, tz_name)
    await state.update_data(return_to_browser=return_to_browser)
    return True, None


async def _start_edit_calendar_step(
    message: Message,
    state: FSMContext,
    event_id: int,
    tz_name: str,
) -> None:
    today, max_date = calendar_bounds(tz_name)
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

    step_text = format_step_with_tz(STEP_EDIT_DATE, tz_name)

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
    await database.update_event_notes(event_id, None)
    await cancel_event_jobs(event_id)
    await schedule_event_jobs(event_id, new_dt, user_id)
    await bump_metric("edit_success")
    if not data.get("return_to_browser"):
        await state.clear()
    return True, None


async def _complete_edit_result(
    message: Message,
    state: FSMContext,
    *,
    user_id: int,
    text: str,
) -> None:
    restored = await return_to_browser_context(
        message,
        state,
        user_id=user_id,
        notice_text=text,
    )
    if not restored:
        await state.clear()
        await message.answer(text, reply_markup=MAIN_MENU)


@router.message(EditEventStates.edit_menu, F.text == "Отмена")
@router.message(EditEventStates.edit_waiting_calendar_date, F.text == "Отмена")
@router.message(EditEventStates.edit_waiting_time, F.text == "Отмена")
@router.message(EditEventStates.edit_confirm_duplicate, F.text == "Отмена")
@router.message(EditEventStates.edit_waiting_activity, F.text == "Отмена")
async def cancel_edit_by_text(message: Message, state: FSMContext) -> None:
    await _complete_edit_result(
        message,
        state,
        user_id=message.from_user.id,  # type: ignore[union-attr]
        text=MSG_EDIT_CANCELLED,
    )


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
        await callback.answer()
        if callback.message:
            await _complete_edit_result(
                callback.message,
                state,
                user_id=user_id,
                text=MSG_EDIT_CANCELLED,
            )
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
        await callback.answer()
        if callback.message:
            await _complete_edit_result(
                callback.message,
                state,
                user_id=user_id,
                text=MSG_EDIT_CANCELLED,
            )
        return

    if callback.message is None:
        await callback.answer(MSG_INVALID_ACTION)
        return

    today, max_date = calendar_bounds(tz_name)

    if kind == "nav":
        if callback.message.message_id != data.get("edit_cal_message_id"):
            await bump_metric("callback_stale_session")
            await callback.answer(MSG_STALE_CALENDAR)
            return

        shift = -1 if parsed["direction"] == "prev" else 1
        new_year, new_month = month_shift(parsed["year"], parsed["month"], shift)
        new_year, new_month = clamp_month_to_bounds(
            new_year,
            new_month,
            min_date=today,
            max_date=max_date,
        )

        kb = build_date_calendar_kb(
            expected_sid,
            new_year,
            new_month,
            today,
            max_date,
            selected_date=state_iso_date(data, "edit_selected_date_iso"),
            today_date=today,
            prefix="edtcal2",
            tail_parts=(str(expected_event_id),),
        )
        text = format_step_with_tz(STEP_EDIT_DATE, tz_name)

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
            quick = quick_date(parsed["value"], today)
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
            format_step_with_tz(STEP_EDIT_TIME, tz_name),
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
        await callback.answer()
        if callback.message:
            await _complete_edit_result(
                callback.message,
                state,
                user_id=user_id,
                text=MSG_EDIT_CANCELLED,
            )
        return

    if kind != "time":
        await callback.answer(MSG_INVALID_ACTION)
        return

    if parsed["value"] == "picker":
        if not data.get("edit_selected_date_iso"):
            await bump_metric("callback_stale_session")
            await callback.answer(MSG_STALE_CALENDAR)
            if callback.message:
                await callback.message.answer(MSG_PICK_DATE_WITH_BUTTONS)
            return
        await callback.answer()
        if callback.message:
            await _open_edit_time_picker(callback.message, state, tz_name=tz_name)
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
                    reply_markup=build_duplicate_warning_kb(data["edit_dup_sid"]),
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
        selected_date = date.fromisoformat(data["edit_selected_date_iso"])
        new_dt = datetime(
            selected_date.year,
            selected_date.month,
            selected_date.day,
            hour,
            minute,
            tzinfo=ZoneInfo(tz_name),
        )
        summary = format_saved_summary(dt=new_dt, activity=event["activity"])
        await _complete_edit_result(
            callback.message,
            state,
            user_id=user_id,
            text=summary,
        )


@router.callback_query(EditEventStates.edit_waiting_time, F.data.startswith("tmr2:"))
async def on_edit_time_picker(callback: CallbackQuery, state: FSMContext) -> None:
    ctx = await resolve_picker_context(
        callback,
        state,
        debounce_check=is_debounced,
        bump_metric=bump_metric,
        sid_key="edit_tp_sid",
        tz_key="edit_timezone",
        hour_key="edit_tp_hour",
        minute_key="edit_tp_minute",
    )
    if ctx is None:
        return

    if ctx.kind == "noop":
        await callback.answer()
        return

    if ctx.kind == "cancel":
        await state.update_data(edit_tp_sid=None, edit_tp_message_id=None)
        await callback.answer()
        cal_sid = ctx.data.get("edit_cal_session_id")
        event_id = ctx.data.get("edit_event_id")
        if not cal_sid or not event_id:
            await bump_metric("callback_stale_session")
            await callback.message.answer(MSG_STALE_CALENDAR)
            return
        await callback.message.answer(
            format_step_with_tz(STEP_EDIT_TIME, ctx.tz_name),
            reply_markup=build_quick_time_kb(
                cal_sid,
                prefix="edtcal2",
                tail_parts=(str(event_id),),
            ),
        )
        return

    if ctx.kind == "ok":
        ok, error = await _apply_edit_datetime(
            state,
            callback.from_user.id,  # type: ignore[union-attr]
            ctx.hour,
            ctx.minute,
        )
        if not ok:
            if error == "DUPLICATE":
                data = await state.get_data()
                await bump_metric("duplicate_warning_shown")
                await callback.answer()
                await callback.message.answer(
                    MSG_DUPLICATE_WARNING,
                    reply_markup=build_duplicate_warning_kb(data["edit_dup_sid"]),
                )
                return
            await callback.answer()
            await callback.message.answer(error or MSG_INVALID_ACTION)
            return

        await callback.answer()
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except TelegramBadRequest:
            pass
        data = await state.get_data()
        event_id = data.get("edit_event_id")
        summary = None
        if event_id:
            updated_event = await database.get_active_event_for_user(
                int(event_id),
                callback.from_user.id,  # type: ignore[union-attr]
            )
            if updated_event:
                summary = format_saved_summary(
                    dt=datetime.fromisoformat(updated_event["event_dt"]),
                    activity=updated_event["activity"],
                )
        await _complete_edit_result(
            callback.message,
            state,
            user_id=callback.from_user.id,  # type: ignore[union-attr]
            text=summary or "Сохранено.",
        )
        return

    await apply_picker_delta_and_render(
        callback,
        state,
        ctx,
        hour_key="edit_tp_hour",
        minute_key="edit_tp_minute",
        render_text=_time_picker_text,
    )


@router.message(EditEventStates.edit_waiting_calendar_date)
async def waiting_edit_calendar_date_text_fallback(message: Message) -> None:
    await reply_pick_date_hint(message)


@router.message(EditEventStates.edit_waiting_time)
async def process_edit_time_manual(message: Message, state: FSMContext) -> None:
    await reply_pick_time_hint(message)


@router.callback_query(EditEventStates.edit_confirm_duplicate, F.data.startswith("dup2:"))
async def on_edit_duplicate_decision(callback: CallbackQuery, state: FSMContext) -> None:
    parsed = parse_duplicate_callback(callback.data or "")
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
        summary = None
        if event_id:
            updated_event = await database.get_active_event_for_user(
                int(event_id),
                callback.from_user.id,  # type: ignore[union-attr]
            )
            if updated_event:
                summary = format_saved_summary(
                    dt=datetime.fromisoformat(updated_event["event_dt"]),
                    activity=updated_event["activity"],
                )
        await _complete_edit_result(
            callback.message,
            state,
            user_id=callback.from_user.id,  # type: ignore[union-attr]
            text=summary or "Сохранено.",
        )


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
    await database.update_event_notes(event_id, None)
    await bump_metric("edit_success")
    summary = format_saved_summary(
        dt=datetime.fromisoformat(event["event_dt"]),
        activity=text,
    )
    await _complete_edit_result(message, state, user_id=user_id, text=summary)


@router.message(EditEventStates.edit_menu)
async def edit_menu_fallback(message: Message) -> None:
    await message.answer(MSG_EDIT_MENU_FALLBACK)
