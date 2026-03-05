"""Shared helpers for inline time-picker callback flows."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from .texts import MSG_DEBOUNCE, MSG_INVALID_ACTION, MSG_STALE_CALENDAR
from .time_picker import apply_picker_action, build_time_picker_kb, parse_time_picker_callback


MetricFn = Callable[[str], Awaitable[None]]
DebounceFn = Callable[[int], bool]
RenderFn = Callable[[str, int, int], str]


@dataclass(slots=True)
class PickerContext:
    kind: str
    parsed: dict
    data: dict
    sid: str
    tz_name: str
    hour: int
    minute: int


async def resolve_picker_context(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    debounce_check: DebounceFn,
    bump_metric: MetricFn,
    sid_key: str,
    tz_key: str,
    hour_key: str,
    minute_key: str,
) -> PickerContext | None:
    """Parse and validate picker callback + state context."""
    user_id = callback.from_user.id  # type: ignore[union-attr]
    if debounce_check(user_id):
        await bump_metric("callback_debounce_reject")
        await callback.answer(MSG_DEBOUNCE)
        return None

    payload = parse_time_picker_callback(callback.data or "")
    if payload is None:
        await bump_metric("callback_invalid_payload")
        await callback.answer(MSG_INVALID_ACTION)
        return None

    kind, parsed = payload
    data = await state.get_data()
    expected_sid = data.get(sid_key)
    tz_name = data.get(tz_key)

    if not expected_sid or not tz_name:
        await bump_metric("callback_stale_session")
        await callback.answer(MSG_STALE_CALENDAR)
        return None

    if parsed.get("sid") != expected_sid:
        await bump_metric("callback_stale_session")
        await callback.answer(MSG_STALE_CALENDAR)
        return None

    if callback.message is None:
        await bump_metric("callback_invalid_payload")
        await callback.answer(MSG_INVALID_ACTION)
        return None

    return PickerContext(
        kind=kind,
        parsed=parsed,
        data=data,
        sid=expected_sid,
        tz_name=tz_name,
        hour=int(data.get(hour_key, 0)),
        minute=int(data.get(minute_key, 0)),
    )


async def apply_picker_delta_and_render(
    callback: CallbackQuery,
    state: FSMContext,
    context: PickerContext,
    *,
    hour_key: str,
    minute_key: str,
    render_text: RenderFn,
) -> tuple[int, int]:
    """Apply picker action and re-render picker screen in place."""
    hour, minute = apply_picker_action(
        context.hour,
        context.minute,
        context.kind,
        context.parsed.get("value"),
        tz_name=context.tz_name,
    )
    await state.update_data(**{hour_key: hour, minute_key: minute})
    try:
        await callback.message.edit_text(
            render_text(context.tz_name, hour, minute),  # type: ignore[union-attr]
            reply_markup=build_time_picker_kb(context.sid, hour, minute),
        )
    except TelegramBadRequest:
        pass
    await callback.answer()
    return hour, minute
