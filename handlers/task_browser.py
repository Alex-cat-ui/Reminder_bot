"""Interactive task browser: filters + pagination in one message."""

from __future__ import annotations

import math
import re
import secrets
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

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
from .time_picker import (
    build_time_picker_kb,
    picker_initial_now,
)
from .ui_common import format_step_with_tz, format_time_picker_text
from .ui_tokens import CANCEL_TEXT, STYLE_DANGER
from .texts import (
    MSG_BROWSER_CLOSED,
    MSG_BROWSER_CONTEXT_LOST,
    MSG_BROWSER_EMPTY,
    MSG_CALENDAR_UPDATED,
    MSG_CLONE_CALENDAR_STEP,
    MSG_DEBOUNCE,
    MSG_DELETED,
    MSG_DELETED_WITH_UNDO,
    MSG_DUPLICATE_WARNING,
    MSG_EDIT_CANCELLED,
    MSG_INVALID_ACTION,
    MSG_PICK_DATE_WITH_BUTTONS,
    MSG_SET_TZ_FIRST,
    MSG_STALE_CALENDAR,
    MSG_CLONE_TIME_STEP,
    MSG_TIME_PAST,
    MSG_UNAUTHORIZED,
    MSG_UNDO_EXPIRED,
    MSG_UNDO_RESTORED,
    format_event_preview,
    format_saved_summary,
)

router = Router()


class BrowserStates(StatesGroup):
    viewing = State()
    clone_waiting_calendar_date = State()
    clone_waiting_time = State()
    clone_confirm = State()


FILTER_RU = {
    "today": "Сегодня",
    "tomorrow": "Завтра",
    "week": "Следующие 7 дней",
    "all": "Все",
}

PAGE_SIZE = 5


# ---------- Browser list ----------

def _bounds_for_filter(filter_name: str, now: datetime) -> tuple[str | None, str | None]:
    if filter_name == "all":
        return None, None

    start_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_today = now.replace(hour=23, minute=59, second=59, microsecond=0)

    if filter_name == "today":
        return start_today.isoformat(), end_today.isoformat()

    if filter_name == "tomorrow":
        start_tomorrow = start_today + timedelta(days=1)
        end_tomorrow = end_today + timedelta(days=1)
        return start_tomorrow.isoformat(), end_tomorrow.isoformat()

    # week = rolling window: now .. now+7 days
    end_week = now + timedelta(days=7)
    return now.isoformat(), end_week.isoformat()


def _short_activity(text: str) -> str:
    t = text.strip()
    return t if len(t) <= 60 else t[:57] + "..."


def _parse_browser_callback(data: str) -> tuple[str, dict] | None:
    parts = data.split(":")
    if len(parts) < 3 or parts[0] != "br2":
        return None

    sid = parts[1]
    if len(parts) == 3 and parts[2] == "close":
        return "close", {"sid": sid}

    if len(parts) == 6 and parts[2] == "f" and parts[4] == "p":
        filter_name = parts[3]
        page_str = parts[5]
        if filter_name not in FILTER_RU:
            return None
        if not page_str.lstrip("-").isdigit():
            return None
        return "page", {"sid": sid, "filter": filter_name, "page": int(page_str)}

    if len(parts) == 4 and parts[2] in {"edit", "clone", "delete"} and parts[3].isdigit():
        return parts[2], {"sid": sid, "event_id": int(parts[3])}

    return None


async def _build_browser_payload(
    *,
    user_id: int,
    tz_name: str,
    sid: str,
    filter_name: str,
    page: int,
) -> tuple[str, InlineKeyboardMarkup, int, int]:
    tz = ZoneInfo(tz_name)
    now = datetime.now(tz)
    start_dt, end_dt = _bounds_for_filter(filter_name, now)

    total_items = await database.count_events_by_filter(
        user_id,
        filter_name,
        start_dt or "",
        end_dt or "",
    )
    total_pages = max(1, math.ceil(total_items / PAGE_SIZE))
    page = max(1, min(page, total_pages))
    offset = (page - 1) * PAGE_SIZE

    events = await database.list_events_by_filter(
        user_id,
        filter_name,
        start_dt,
        end_dt,
        PAGE_SIZE,
        offset,
    )

    page_count = len(events)
    header = f"Фильтр: {FILTER_RU[filter_name]} | {page_count} из {total_items}"
    lines = [header, f"Страница {page}/{total_pages}", ""]

    if not events:
        lines.append(MSG_BROWSER_EMPTY)
    else:
        for idx, ev in enumerate(events, start=offset + 1):
            dt = datetime.fromisoformat(ev["event_dt"])
            lines.append(
                f"{idx}. {dt.strftime('%d.%m.%Y %H:%M')}\n"
                f"Активность: {_short_activity(ev['activity'])}"
            )
            lines.append("")

    text = "\n".join(lines).strip()

    kb_rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(text="Сегодня", callback_data=f"br2:{sid}:f:today:p:1"),
            InlineKeyboardButton(text="Завтра", callback_data=f"br2:{sid}:f:tomorrow:p:1"),
            InlineKeyboardButton(text="7 дней", callback_data=f"br2:{sid}:f:week:p:1"),
            InlineKeyboardButton(text="Все", callback_data=f"br2:{sid}:f:all:p:1"),
        ],
        [
            InlineKeyboardButton(
                text="←",
                callback_data=f"br2:{sid}:f:{filter_name}:p:{max(1, page - 1)}",
            ),
            InlineKeyboardButton(
                text=f"{page}/{total_pages}",
                callback_data=f"br2:{sid}:f:{filter_name}:p:{page}",
            ),
            InlineKeyboardButton(
                text="→",
                callback_data=f"br2:{sid}:f:{filter_name}:p:{min(total_pages, page + 1)}",
            ),
        ],
    ]

    for idx, ev in enumerate(events, start=offset + 1):
        kb_rows.append(
            [
                InlineKeyboardButton(text=f"Изменить #{idx}", callback_data=f"br2:{sid}:edit:{ev['id']}"),
                InlineKeyboardButton(text=f"Повторить #{idx}", callback_data=f"br2:{sid}:clone:{ev['id']}"),
            ]
        )
        kb_rows.append(
            [InlineKeyboardButton(text=f"Удалить #{idx}", callback_data=f"br2:{sid}:delete:{ev['id']}")]
        )

    kb_rows.append([InlineKeyboardButton(text="Закрыть", callback_data=f"br2:{sid}:close")])

    return text, InlineKeyboardMarkup(inline_keyboard=kb_rows), page, total_pages


async def _refresh_browser_message(callback: CallbackQuery, state: FSMContext, *, user_id: int) -> None:
    data = await state.get_data()
    sid = data.get("browser_sid")
    filter_name = data.get("browser_filter", "week")
    page = int(data.get("browser_page", 1))
    tz_name = data.get("browser_timezone")

    if not sid or not tz_name or callback.message is None:
        return

    text, kb, page, _ = await _build_browser_payload(
        user_id=user_id,
        tz_name=tz_name,
        sid=sid,
        filter_name=filter_name,
        page=page,
    )
    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except TelegramBadRequest:
        return

    await state.set_state(BrowserStates.viewing)
    await state.update_data(browser_filter=filter_name, browser_page=page)


def _extract_browser_context(data: dict) -> tuple[str, str, int, str, int] | None:
    sid = data.get("browser_sid")
    filter_name = data.get("browser_filter")
    page_raw = data.get("browser_page")
    tz_name = data.get("browser_timezone")
    message_id_raw = data.get("browser_message_id")

    if not sid or not isinstance(sid, str):
        return None
    if filter_name not in FILTER_RU:
        return None
    if not tz_name or not isinstance(tz_name, str):
        return None

    try:
        page = int(page_raw)
        message_id = int(message_id_raw)
    except (TypeError, ValueError):
        return None

    if page < 1 or message_id < 1:
        return None

    return sid, filter_name, page, tz_name, message_id


async def return_to_browser_context(
    message: Message,
    state: FSMContext,
    *,
    user_id: int,
    notice_text: str | None = None,
) -> bool:
    data = await state.get_data()
    if not data.get("return_to_browser"):
        return False

    ctx = _extract_browser_context(data)
    if ctx is None:
        await state.clear()
        await message.answer(MSG_BROWSER_CONTEXT_LOST, reply_markup=MAIN_MENU)
        return True

    sid, filter_name, requested_page, tz_name, browser_message_id = ctx
    text, kb, page, _ = await _build_browser_payload(
        user_id=user_id,
        tz_name=tz_name,
        sid=sid,
        filter_name=filter_name,
        page=requested_page,
    )

    new_message_id = browser_message_id
    try:
        await message.bot.edit_message_text(
            text=text,
            chat_id=message.chat.id,
            message_id=browser_message_id,
            reply_markup=kb,
        )
    except TelegramBadRequest as exc:
        lowered = str(exc).lower()
        if "message is not modified" not in lowered:
            if "message to edit not found" in lowered:
                sent = await message.answer(text, reply_markup=kb)
                new_message_id = sent.message_id
            else:
                await state.clear()
                await message.answer(MSG_BROWSER_CONTEXT_LOST, reply_markup=MAIN_MENU)
                return True

    await state.clear()
    await state.set_state(BrowserStates.viewing)
    await state.update_data(
        return_to_browser=True,
        browser_sid=sid,
        browser_filter=filter_name,
        browser_page=page,
        browser_timezone=tz_name,
        browser_message_id=new_message_id,
    )

    if notice_text:
        await message.answer(notice_text)
    return True


async def start_tasks_browser(
    message: Message,
    state: FSMContext,
    *,
    default_filter: str = "week",
) -> None:
    user_id = message.from_user.id  # type: ignore[union-attr]
    user = await database.get_user(user_id)
    if not user:
        await message.answer(MSG_SET_TZ_FIRST)
        return

    sid = new_calendar_session_id()
    tz_name = user["timezone"]

    text, kb, page, _ = await _build_browser_payload(
        user_id=user_id,
        tz_name=tz_name,
        sid=sid,
        filter_name=default_filter,
        page=1,
    )

    await state.set_state(BrowserStates.viewing)
    await state.update_data(
        return_to_browser=True,
        browser_sid=sid,
        browser_filter=default_filter,
        browser_page=page,
        browser_timezone=tz_name,
    )

    sent = await message.answer(text, reply_markup=kb)
    await state.update_data(browser_message_id=sent.message_id)


@router.message(Command("tasks"))
async def cmd_tasks(message: Message, state: FSMContext) -> None:
    await start_tasks_browser(message, state, default_filter="all")


# ---------- Browser callbacks ----------

@router.callback_query(F.data.startswith("br2:"))
async def on_browser_callback(callback: CallbackQuery, state: FSMContext) -> None:
    user_id = callback.from_user.id  # type: ignore[union-attr]
    if is_debounced(user_id):
        await bump_metric("callback_debounce_reject")
        await callback.answer(MSG_DEBOUNCE)
        return

    parsed = _parse_browser_callback(callback.data or "")
    if parsed is None:
        await bump_metric("callback_invalid_payload")
        await callback.answer(MSG_INVALID_ACTION)
        return

    kind, payload = parsed
    data = await state.get_data()

    sid = payload["sid"]
    if data.get("browser_sid") != sid:
        await bump_metric("callback_stale_session")
        await callback.answer(MSG_STALE_CALENDAR)
        return

    if callback.message is None:
        await bump_metric("callback_invalid_payload")
        await callback.answer(MSG_INVALID_ACTION)
        return

    if kind == "close":
        try:
            await callback.message.edit_text(MSG_BROWSER_CLOSED, reply_markup=None)
        except TelegramBadRequest:
            pass
        await state.clear()
        await callback.answer()
        return

    tz_name = data.get("browser_timezone")
    if not tz_name:
        await callback.answer(MSG_SET_TZ_FIRST)
        return

    if kind == "page":
        if callback.message.message_id != data.get("browser_message_id"):
            await bump_metric("callback_stale_session")
            await callback.answer(MSG_STALE_CALENDAR)
            return

        filter_name = payload["filter"]
        requested_page = payload["page"]
        text, kb, page, _ = await _build_browser_payload(
            user_id=user_id,
            tz_name=tz_name,
            sid=sid,
            filter_name=filter_name,
            page=requested_page,
        )
        try:
            await callback.message.edit_text(text, reply_markup=kb)
        except TelegramBadRequest as exc:
            lowered = str(exc).lower()
            if "message is not modified" in lowered:
                await callback.answer()
                return
            if "message to edit not found" in lowered:
                sent = await callback.message.answer(text, reply_markup=kb)
                await state.update_data(browser_message_id=sent.message_id)
                await callback.answer(MSG_CALENDAR_UPDATED)
                return
            await callback.answer(MSG_INVALID_ACTION)
            return

        await state.set_state(BrowserStates.viewing)
        await state.update_data(browser_filter=filter_name, browser_page=page)
        await callback.answer()
        return

    event_id = payload["event_id"]
    event = await database.get_active_event_for_user(event_id, user_id)
    if event is None:
        await bump_metric("ownership_reject")
        await callback.answer(MSG_UNAUTHORIZED, show_alert=True)
        return

    if kind == "edit":
        from .event_edit import start_edit_menu_for_event

        await state.update_data(return_to_browser=True)
        ok, error = await start_edit_menu_for_event(
            callback.message,
            state,
            user_id=user_id,
            event_id=event_id,
            return_to_browser=True,
        )
        await callback.answer()
        if not ok and error:
            await callback.message.answer(error)
        return

    if kind == "clone":
        await callback.answer()
        await state.update_data(return_to_browser=True)
        await _start_clone_calendar_step(
            callback.message,
            state,
            user_id=user_id,
            source_event=event,
            tz_name=tz_name,
        )
        return

    if kind == "delete":
        await database.update_event_status(event_id, "deleted")
        await cancel_event_jobs(event_id)
        await bump_metric("delete_performed")

        token = secrets.token_hex(6)
        expires_at = (datetime.utcnow() + timedelta(minutes=15)).isoformat()
        await database.create_undo_action(event_id, user_id, token, expires_at)

        await _refresh_browser_message(callback, state, user_id=user_id)
        await callback.answer(MSG_DELETED)
        await callback.message.answer(
            MSG_DELETED_WITH_UNDO,
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="Отменить удаление", callback_data=f"undo2:{token}")]]
            ),
        )
        return

    await callback.answer(MSG_INVALID_ACTION)


# ---------- Undo ----------

_TOKEN_RE = re.compile(r"^[0-9a-f]{12}$")


@router.callback_query(F.data.startswith("undo2:"))
async def on_undo_callback(callback: CallbackQuery, state: FSMContext | None = None) -> None:
    token = (callback.data or "").split(":", 1)[1] if ":" in (callback.data or "") else ""
    if _TOKEN_RE.match(token) is None:
        await bump_metric("callback_invalid_payload")
        await callback.answer(MSG_INVALID_ACTION, show_alert=True)
        return

    undo = await database.get_undo_action(token)
    if not undo or undo["status"] != "active":
        await bump_metric("undo_expired")
        await callback.answer(MSG_UNDO_EXPIRED, show_alert=True)
        return

    user_id = callback.from_user.id  # type: ignore[union-attr]
    if undo["user_id"] != user_id:
        await bump_metric("ownership_reject")
        await callback.answer(MSG_UNAUTHORIZED, show_alert=True)
        return

    expires_at = datetime.fromisoformat(undo["expires_at"])
    now_utc = datetime.utcnow()
    if now_utc > expires_at:
        await database.mark_undo_action_expired(token)
        await bump_metric("undo_expired")
        await callback.answer(MSG_UNDO_EXPIRED, show_alert=True)
        return

    event = await database.get_event(undo["event_id"])
    if not event or event["status"] != "deleted":
        await bump_metric("undo_expired")
        await callback.answer(MSG_UNDO_EXPIRED, show_alert=True)
        return

    await database.update_event_status(undo["event_id"], "active")
    await database.mark_undo_action_used(token, now_utc.isoformat())

    event_dt = datetime.fromisoformat(event["event_dt"])
    await schedule_event_jobs(undo["event_id"], event_dt, user_id)
    await bump_metric("undo_success")

    await callback.answer(MSG_UNDO_RESTORED)
    if callback.message:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except TelegramBadRequest:
            pass
        restored = False
        if state is not None:
            restored = await return_to_browser_context(
                callback.message,
                state,
                user_id=user_id,
                notice_text=MSG_UNDO_RESTORED,
            )
        if not restored:
            await callback.message.answer(MSG_UNDO_RESTORED)


# ---------- Clone flow ----------

def _clone_confirm_kb(sid: str, source_event_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Создать копию", callback_data=f"cln2:{sid}:confirm:{source_event_id}")],
            [
                InlineKeyboardButton(
                    text=CANCEL_TEXT,
                    callback_data=f"cln2:{sid}:cancel_confirm:{source_event_id}",
                    style=STYLE_DANGER,
                )
            ],
        ]
    )


async def _start_clone_calendar_step(
    message: Message,
    state: FSMContext,
    *,
    user_id: int,
    source_event: dict,
    tz_name: str,
) -> None:
    today, max_date = calendar_bounds(tz_name)
    sid = new_calendar_session_id()

    await state.set_state(BrowserStates.clone_waiting_calendar_date)
    await state.update_data(
        clone_sid=sid,
        clone_source_event_id=source_event["id"],
        clone_timezone=tz_name,
        clone_selected_date_iso=None,
        clone_activity=source_event["activity"],
        clone_dup_sid=None,
        clone_dup_override=False,
    )

    step_text = format_step_with_tz(MSG_CLONE_CALENDAR_STEP, tz_name)
    kb = build_date_calendar_kb(
        sid,
        today.year,
        today.month,
        today,
        max_date,
        selected_date=None,
        today_date=today,
        prefix="cln2",
        tail_parts=(str(source_event["id"]),),
    )
    sent = await message.answer(step_text, reply_markup=kb)
    await state.update_data(clone_message_id=sent.message_id)


async def _open_clone_time_picker(message: Message, state: FSMContext, *, tz_name: str) -> None:
    sid = new_calendar_session_id()
    hour, minute = picker_initial_now(tz_name)
    await state.update_data(clone_tp_sid=sid, clone_tp_hour=hour, clone_tp_minute=minute)
    sent = await message.answer(
        format_time_picker_text(MSG_CLONE_TIME_STEP, tz_name, hour, minute),
        reply_markup=build_time_picker_kb(sid, hour, minute),
    )
    await state.update_data(clone_tp_message_id=sent.message_id)


async def _apply_clone_time(
    state: FSMContext,
    *,
    user_id: int,
    hour: int,
    minute: int,
) -> tuple[bool, str | None]:
    data = await state.get_data()
    selected_iso = data.get("clone_selected_date_iso")
    tz_name = data.get("clone_timezone")

    if not selected_iso or not tz_name:
        return False, MSG_STALE_CALENDAR

    selected_date = date.fromisoformat(selected_iso)
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

    await state.update_data(clone_event_dt_iso=dt.isoformat())
    await state.set_state(BrowserStates.clone_confirm)
    return True, None


async def _finalize_clone(state: FSMContext, user_id: int) -> tuple[bool, str | None]:
    data = await state.get_data()
    dt_iso = data.get("clone_event_dt_iso")
    activity = data.get("clone_activity")

    if not dt_iso or not activity:
        return False, MSG_INVALID_ACTION

    duplicate = await has_duplicate_event(
        user_id=user_id,
        event_dt_iso=dt_iso,
        activity=activity,
    )
    if duplicate and not data.get("clone_dup_override"):
        dup_sid = new_calendar_session_id()
        await state.update_data(clone_dup_sid=dup_sid)
        return False, "DUPLICATE"

    dt = datetime.fromisoformat(dt_iso)
    event_id = await database.create_event(
        user_id=user_id,
        event_dt=dt_iso,
        activity=activity,
        notes=None,
    )
    await schedule_event_jobs(event_id, dt, user_id)
    await bump_metric("clone_created")
    if not data.get("return_to_browser"):
        await state.clear()
    return True, None


@router.message(BrowserStates.clone_waiting_calendar_date, F.text == "Отмена")
@router.message(BrowserStates.clone_waiting_time, F.text == "Отмена")
@router.message(BrowserStates.clone_confirm, F.text == "Отмена")
async def cancel_clone_by_text(message: Message, state: FSMContext) -> None:
    restored = await return_to_browser_context(
        message,
        state,
        user_id=message.from_user.id,  # type: ignore[union-attr]
        notice_text=MSG_EDIT_CANCELLED,
    )
    if not restored:
        await state.clear()
        await message.answer(MSG_EDIT_CANCELLED, reply_markup=MAIN_MENU)


@router.callback_query(BrowserStates.clone_waiting_calendar_date, F.data.startswith("cln2:"))
async def on_clone_calendar(callback: CallbackQuery, state: FSMContext) -> None:
    user_id = callback.from_user.id  # type: ignore[union-attr]
    if is_debounced(user_id):
        await bump_metric("callback_debounce_reject")
        await callback.answer(MSG_DEBOUNCE)
        return

    payload = parse_calendar_callback_with_event(callback.data or "", prefix="cln2")
    if payload is None:
        await bump_metric("callback_invalid_payload")
        await callback.answer(MSG_INVALID_ACTION)
        return

    kind, parsed = payload
    data = await state.get_data()
    sid = data.get("clone_sid")
    source_event_id = data.get("clone_source_event_id")
    tz_name = data.get("clone_timezone")

    if not sid or not source_event_id or not tz_name:
        await bump_metric("callback_stale_session")
        await callback.answer(MSG_STALE_CALENDAR)
        return

    if parsed["sid"] != sid or parsed["event_id"] != source_event_id:
        await bump_metric("callback_stale_session")
        await callback.answer(MSG_STALE_CALENDAR)
        return

    if kind == "noop":
        await callback.answer()
        return

    if kind == "cancel":
        await callback.answer()
        if callback.message:
            restored = await return_to_browser_context(
                callback.message,
                state,
                user_id=user_id,
                notice_text=MSG_EDIT_CANCELLED,
            )
            if not restored:
                await state.clear()
                await callback.message.answer(MSG_EDIT_CANCELLED, reply_markup=MAIN_MENU)
        return

    if callback.message is None:
        await callback.answer(MSG_INVALID_ACTION)
        return

    today, max_date = calendar_bounds(tz_name)

    if kind == "nav":
        if callback.message.message_id != data.get("clone_message_id"):
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

        selected_date = state_iso_date(data, "clone_selected_date_iso")
        kb = build_date_calendar_kb(
            sid,
            new_year,
            new_month,
            today,
            max_date,
            selected_date=selected_date,
            today_date=today,
            prefix="cln2",
            tail_parts=(str(source_event_id),),
        )
        text = format_step_with_tz(MSG_CLONE_CALENDAR_STEP, tz_name)

        try:
            await callback.message.edit_text(text, reply_markup=kb)
        except TelegramBadRequest as exc:
            lowered = str(exc).lower()
            if "message is not modified" in lowered:
                await callback.answer()
                return
            if "message to edit not found" in lowered:
                sent = await callback.message.answer(text, reply_markup=kb)
                await state.update_data(clone_message_id=sent.message_id)
                await callback.answer(MSG_CALENDAR_UPDATED)
                return
            await callback.answer(MSG_INVALID_ACTION)
            return

        await callback.answer()
        return

    if kind in {"day", "quick"}:
        if kind == "day":
            selected = parsed["date"]
        else:
            selected = quick_date(parsed["value"], today)
            if selected is None:
                await callback.answer(MSG_INVALID_ACTION)
                return

        if selected < today or selected > max_date:
            await callback.answer(MSG_INVALID_ACTION)
            return

        await state.update_data(clone_selected_date_iso=selected.isoformat())
        await state.set_state(BrowserStates.clone_waiting_time)

        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except TelegramBadRequest:
            pass

        await callback.answer()
        await callback.message.answer(
            format_step_with_tz(MSG_CLONE_TIME_STEP, tz_name),
            reply_markup=build_quick_time_kb(
                sid,
                prefix="cln2",
                tail_parts=(str(source_event_id),),
            ),
        )
        return

    await callback.answer(MSG_INVALID_ACTION)


@router.callback_query(BrowserStates.clone_waiting_time, F.data.startswith("cln2:"))
async def on_clone_time(callback: CallbackQuery, state: FSMContext) -> None:
    user_id = callback.from_user.id  # type: ignore[union-attr]
    if is_debounced(user_id):
        await bump_metric("callback_debounce_reject")
        await callback.answer(MSG_DEBOUNCE)
        return

    payload = parse_calendar_callback_with_event(callback.data or "", prefix="cln2")
    if payload is None:
        await bump_metric("callback_invalid_payload")
        await callback.answer(MSG_INVALID_ACTION)
        return

    kind, parsed = payload
    data = await state.get_data()
    sid = data.get("clone_sid")
    source_event_id = data.get("clone_source_event_id")
    tz_name = data.get("clone_timezone")

    if not sid or not source_event_id or not tz_name:
        await bump_metric("callback_stale_session")
        await callback.answer(MSG_STALE_CALENDAR)
        return

    if parsed["sid"] != sid or parsed["event_id"] != source_event_id:
        await bump_metric("callback_stale_session")
        await callback.answer(MSG_STALE_CALENDAR)
        return

    if kind == "noop":
        await callback.answer()
        return

    if kind == "cancel":
        await callback.answer()
        if callback.message:
            restored = await return_to_browser_context(
                callback.message,
                state,
                user_id=user_id,
                notice_text=MSG_EDIT_CANCELLED,
            )
            if not restored:
                await state.clear()
                await callback.message.answer(MSG_EDIT_CANCELLED, reply_markup=MAIN_MENU)
        return

    if kind != "time":
        await callback.answer(MSG_INVALID_ACTION)
        return

    if parsed["value"] == "picker":
        if not data.get("clone_selected_date_iso"):
            await bump_metric("callback_stale_session")
            await callback.answer(MSG_STALE_CALENDAR)
            if callback.message:
                await callback.message.answer(MSG_PICK_DATE_WITH_BUTTONS)
            return
        await callback.answer()
        if callback.message:
            await _open_clone_time_picker(callback.message, state, tz_name=tz_name)
        return

    hhmm = parsed["value"]
    ok, error = await _apply_clone_time(
        state,
        user_id=user_id,
        hour=int(hhmm[:2]),
        minute=int(hhmm[2:]),
    )
    if not ok:
        await callback.answer()
        if callback.message:
            await callback.message.answer(error or MSG_INVALID_ACTION)
        return

    data = await state.get_data()
    dt = datetime.fromisoformat(data["clone_event_dt_iso"])
    preview = format_event_preview(
        dt=dt,
        activity=data["clone_activity"],
        mode="create",
    )

    await callback.answer()
    if callback.message:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except TelegramBadRequest:
            pass
        await callback.message.answer(preview, reply_markup=_clone_confirm_kb(sid, source_event_id))


@router.message(BrowserStates.clone_waiting_time)
async def clone_time_manual(message: Message, state: FSMContext) -> None:
    await reply_pick_time_hint(message)


@router.callback_query(BrowserStates.clone_waiting_time, F.data.startswith("tmr2:"))
async def on_clone_time_picker(callback: CallbackQuery, state: FSMContext) -> None:
    ctx = await resolve_picker_context(
        callback,
        state,
        debounce_check=is_debounced,
        bump_metric=bump_metric,
        sid_key="clone_tp_sid",
        tz_key="clone_timezone",
        hour_key="clone_tp_hour",
        minute_key="clone_tp_minute",
    )
    if ctx is None:
        return

    source_event_id = ctx.data.get("clone_source_event_id")
    clone_sid = ctx.data.get("clone_sid")
    if not source_event_id or not clone_sid:
        await bump_metric("callback_stale_session")
        await callback.answer(MSG_STALE_CALENDAR)
        return

    if ctx.kind == "noop":
        await callback.answer()
        return

    if ctx.kind == "cancel":
        await state.update_data(clone_tp_sid=None, clone_tp_message_id=None)
        await callback.answer()
        await callback.message.answer(
            format_step_with_tz(MSG_CLONE_TIME_STEP, ctx.tz_name),
            reply_markup=build_quick_time_kb(
                clone_sid,
                prefix="cln2",
                tail_parts=(str(source_event_id),),
            ),
        )
        return

    if ctx.kind == "ok":
        ok, error = await _apply_clone_time(
            state,
            user_id=callback.from_user.id,  # type: ignore[union-attr]
            hour=ctx.hour,
            minute=ctx.minute,
        )
        if not ok:
            await callback.answer()
            await callback.message.answer(error or MSG_INVALID_ACTION)
            return

        data = await state.get_data()
        dt = datetime.fromisoformat(data["clone_event_dt_iso"])
        preview = format_event_preview(
            dt=dt,
            activity=data["clone_activity"],
            mode="create",
        )

        await callback.answer()
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except TelegramBadRequest:
            pass
        await callback.message.answer(
            preview,
            reply_markup=_clone_confirm_kb(data["clone_sid"], data["clone_source_event_id"]),
        )
        return

    await apply_picker_delta_and_render(
        callback,
        state,
        ctx,
        hour_key="clone_tp_hour",
        minute_key="clone_tp_minute",
        render_text=lambda tz_name, hour, minute: format_time_picker_text(
            MSG_CLONE_TIME_STEP,
            tz_name,
            hour,
            minute,
        ),
    )


def _parse_clone_confirm_callback(data: str) -> tuple[str, str, int] | None:
    parts = data.split(":")
    if len(parts) != 4 or parts[0] != "cln2":
        return None
    sid = parts[1]
    action = parts[2]
    if action not in {"confirm", "cancel_confirm"}:
        return None
    if not parts[3].isdigit():
        return None
    return action, sid, int(parts[3])


@router.callback_query(BrowserStates.clone_confirm, F.data.startswith("cln2:"))
async def on_clone_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    parsed = _parse_clone_confirm_callback(callback.data or "")
    if parsed is None:
        await bump_metric("callback_invalid_payload")
        await callback.answer(MSG_INVALID_ACTION)
        return

    action, sid, source_event_id = parsed
    data = await state.get_data()

    if sid != data.get("clone_sid") or source_event_id != data.get("clone_source_event_id"):
        await bump_metric("callback_stale_session")
        await callback.answer(MSG_STALE_CALENDAR)
        return

    if action == "cancel_confirm":
        await callback.answer()
        if callback.message:
            restored = await return_to_browser_context(
                callback.message,
                state,
                user_id=callback.from_user.id,  # type: ignore[union-attr]
                notice_text=MSG_EDIT_CANCELLED,
            )
            if not restored:
                await state.clear()
                await callback.message.answer(MSG_EDIT_CANCELLED, reply_markup=MAIN_MENU)
        return

    ok, error = await _finalize_clone(state, callback.from_user.id)  # type: ignore[union-attr]
    if not ok and error == "DUPLICATE":
        data = await state.get_data()
        await bump_metric("duplicate_warning_shown")
        await callback.answer()
        if callback.message:
            await callback.message.answer(
                MSG_DUPLICATE_WARNING,
                reply_markup=build_duplicate_warning_kb(data["clone_dup_sid"]),
            )
        return

    if not ok:
        await callback.answer(error or MSG_INVALID_ACTION)
        return

    summary = format_saved_summary(
        dt=datetime.fromisoformat(data["clone_event_dt_iso"]),
        activity=data["clone_activity"],
    )
    await callback.answer()
    if callback.message:
        restored = await return_to_browser_context(
            callback.message,
            state,
            user_id=callback.from_user.id,  # type: ignore[union-attr]
            notice_text=summary,
        )
        if not restored:
            await state.clear()
            await callback.message.answer(summary, reply_markup=MAIN_MENU)


@router.callback_query(BrowserStates.clone_confirm, F.data.startswith("dup2:"))
async def on_clone_duplicate_decision(callback: CallbackQuery, state: FSMContext) -> None:
    parsed = parse_duplicate_callback(callback.data or "")
    if parsed is None:
        await bump_metric("callback_invalid_payload")
        await callback.answer(MSG_INVALID_ACTION)
        return

    dup_sid, action = parsed
    data = await state.get_data()
    expected = data.get("clone_dup_sid")
    if not expected or expected != dup_sid:
        await bump_metric("callback_stale_session")
        await callback.answer(MSG_STALE_CALENDAR)
        return

    if action == "cancel":
        await callback.answer()
        if callback.message:
            dt_iso = data.get("clone_event_dt_iso")
            tz_name = data.get("clone_timezone")
            activity = data.get("clone_activity")
            sid = data.get("clone_sid")
            source_event_id = data.get("clone_source_event_id")
            if dt_iso and tz_name and activity and sid and source_event_id:
                dt = datetime.fromisoformat(dt_iso)
                preview = format_event_preview(
                    dt=dt,
                    activity=activity,
                    mode="create",
                )
                await callback.message.answer(
                    preview,
                    reply_markup=_clone_confirm_kb(sid, source_event_id),
                )
        return

    await state.update_data(clone_dup_override=True)
    ok, error = await _finalize_clone(state, callback.from_user.id)  # type: ignore[union-attr]
    if not ok:
        await callback.answer(error or MSG_INVALID_ACTION)
        return

    summary = format_saved_summary(
        dt=datetime.fromisoformat(data["clone_event_dt_iso"]),
        activity=data["clone_activity"],
    )
    await bump_metric("duplicate_override_save")
    await callback.answer()
    if callback.message:
        restored = await return_to_browser_context(
            callback.message,
            state,
            user_id=callback.from_user.id,  # type: ignore[union-attr]
            notice_text=summary,
        )
        if not restored:
            await state.clear()
            await callback.message.answer(summary, reply_markup=MAIN_MENU)


@router.message(BrowserStates.clone_waiting_calendar_date)
async def clone_waiting_date_manual(message: Message) -> None:
    await reply_pick_date_hint(message)
