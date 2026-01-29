"""Inline callback handlers: snooze, done, delete."""

from aiogram import Router, F
from aiogram.types import CallbackQuery

import db as database
from scheduler import schedule_snooze, cancel_event_jobs

router = Router()


@router.callback_query(F.data.startswith("snooze:"))
async def on_snooze(callback: CallbackQuery) -> None:
    event_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    ok = await schedule_snooze(event_id)
    if ok:
        await callback.answer("Отложено на 1 час.")
    else:
        await callback.answer("Лимит откладываний достигнут (25).")
        # Remove snooze button — rebuild keyboard without it
        from scheduler import _build_reminder_keyboard
        event = await database.get_event(event_id)
        if event:
            kb = _build_reminder_keyboard(event_id, event["snooze_count"])
            await callback.message.edit_reply_markup(reply_markup=kb)  # type: ignore[union-attr]


@router.callback_query(F.data.startswith("done:"))
async def on_done(callback: CallbackQuery) -> None:
    event_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    await database.update_event_status(event_id, "done")
    await cancel_event_jobs(event_id)
    await callback.message.edit_reply_markup(reply_markup=None)  # type: ignore[union-attr]
    await callback.message.answer("✅ Завершено")  # type: ignore[union-attr]
    await callback.answer()


@router.callback_query(F.data.startswith("delete:"))
async def on_delete(callback: CallbackQuery) -> None:
    event_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    await database.update_event_status(event_id, "deleted")
    await cancel_event_jobs(event_id)
    await callback.message.edit_reply_markup(reply_markup=None)  # type: ignore[union-attr]
    await callback.answer("Удалено.")
