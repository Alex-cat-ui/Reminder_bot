"""Admin metrics command handlers."""

from __future__ import annotations

from datetime import datetime

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

import db as database
from config import ADMIN_USER_IDS

router = Router()

METRIC_KEYS = [
    "ownership_reject",
    "callback_invalid_payload",
    "callback_stale_session",
    "callback_debounce_reject",
    "time_parse_error",
    "time_past_reject",
    "duplicate_warning_shown",
    "duplicate_override_save",
    "undo_success",
    "undo_expired",
    "clone_created",
    "delete_performed",
    "create_success",
    "edit_success",
]


@router.message(Command("metrics_today"))
async def metrics_today(message: Message) -> None:
    user_id = message.from_user.id  # type: ignore[union-attr]
    if user_id not in ADMIN_USER_IDS:
        await message.answer("Доступ запрещен.")
        return

    today = datetime.utcnow().date().isoformat()
    rows = await database.get_metrics_for_day(today)
    data = {r["key"]: r["value"] for r in rows}

    lines = [f"Метрики за {today} (UTC):"]
    for key in METRIC_KEYS:
        lines.append(f"{key}: {data.get(key, 0)}")
    await message.answer("\n".join(lines))
