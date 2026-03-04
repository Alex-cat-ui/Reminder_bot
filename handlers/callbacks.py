"""Inline callback handlers: snooze, done, delete."""

from aiogram import Router, F
from aiogram.types import CallbackQuery

import db as database
from scheduler import schedule_snooze, cancel_event_jobs, _build_reminder_keyboard
from .metrics_utils import bump_metric
from .texts import MSG_DELETED, MSG_DONE, MSG_INVALID_ACTION, MSG_SNOOZE_LIMIT, MSG_UNAUTHORIZED

router = Router()


@router.callback_query(F.data.startswith("snooze:"))
async def on_snooze(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id  # type: ignore[union-attr]
    try:
        event_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    except Exception:
        await bump_metric("callback_invalid_payload")
        await callback.answer(MSG_INVALID_ACTION, show_alert=True)
        return
    event = await database.get_active_event_for_user(event_id, user_id)
    if event is None:
        await bump_metric("ownership_reject")
        await callback.answer(MSG_UNAUTHORIZED, show_alert=True)
        return

    new_time = await schedule_snooze(event_id)
    if new_time:
        time_str = new_time.strftime("%d.%m.%Y %H:%M")
        await callback.answer()
        await callback.message.edit_reply_markup(reply_markup=None)  # type: ignore[union-attr]
        event = await database.get_active_event_for_user(event_id, user_id)
        if event:
            kb = _build_reminder_keyboard(event_id, event["snooze_count"])
            await callback.message.answer(  # type: ignore[union-attr]
                f"Отложено. Следующее напоминание: {time_str}",
                reply_markup=kb,
            )
    else:
        await callback.answer(MSG_SNOOZE_LIMIT)
        event = await database.get_active_event_for_user(event_id, user_id)
        if event:
            kb = _build_reminder_keyboard(event_id, event["snooze_count"])
            await callback.message.edit_reply_markup(reply_markup=kb)  # type: ignore[union-attr]


@router.callback_query(F.data.startswith("done:"))
async def on_done(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id  # type: ignore[union-attr]
    try:
        event_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    except Exception:
        await bump_metric("callback_invalid_payload")
        await callback.answer(MSG_INVALID_ACTION, show_alert=True)
        return
    event = await database.get_active_event_for_user(event_id, user_id)
    if event is None:
        await bump_metric("ownership_reject")
        await callback.answer(MSG_UNAUTHORIZED, show_alert=True)
        return

    await database.update_event_status(event_id, "done")
    await cancel_event_jobs(event_id)
    await callback.message.edit_reply_markup(reply_markup=None)  # type: ignore[union-attr]
    await callback.message.answer(MSG_DONE)  # type: ignore[union-attr]
    await callback.answer()


@router.callback_query(F.data.startswith("delete:"))
async def on_delete(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id  # type: ignore[union-attr]
    try:
        event_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    except Exception:
        await bump_metric("callback_invalid_payload")
        await callback.answer(MSG_INVALID_ACTION, show_alert=True)
        return
    event = await database.get_active_event_for_user(event_id, user_id)
    if event is None:
        await bump_metric("ownership_reject")
        await callback.answer(MSG_UNAUTHORIZED, show_alert=True)
        return

    await database.update_event_status(event_id, "deleted")
    await cancel_event_jobs(event_id)
    await bump_metric("delete_performed")
    await callback.message.edit_reply_markup(reply_markup=None)  # type: ignore[union-attr]
    await callback.answer(MSG_DELETED)
