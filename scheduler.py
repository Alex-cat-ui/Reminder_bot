"""APScheduler integration: schedule reminder jobs for events."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler

import db as database

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

# Will be set by main.py at startup
_bot = None
_db_path: str = "bot.db"


def set_bot(bot, db_path: str = "bot.db") -> None:
    global _bot, _db_path
    _bot = bot
    _db_path = db_path


def compute_job_times(
    event_dt: datetime, now: datetime
) -> list[tuple[str, datetime]]:
    """Return list of (job_type, run_dt) for a given event datetime.

    Rules:
    - day_before: the day before at 12:00 (if > 24h away)
    - hour_before: 1 hour before (if > 60 min away)
    - at_time: exact event time
    - for deltas <= 60 min: schedule only at_time
    """
    jobs: list[tuple[str, datetime]] = []
    delta = event_dt - now

    if delta.total_seconds() <= 0:
        return jobs

    # Near events must not produce parallel close reminders.
    if delta.total_seconds() <= 3600:
        return [("at_time", event_dt)]

    # day_before: run at 12:00 the day before event
    day_before_dt = (event_dt - timedelta(days=1)).replace(
        hour=12, minute=0, second=0, microsecond=0
    )
    if day_before_dt > now:
        jobs.append(("day_before", day_before_dt))

    # hour_before
    hour_before_dt = event_dt - timedelta(hours=1)
    if hour_before_dt > now and delta.total_seconds() > 3600:
        jobs.append(("hour_before", hour_before_dt))

    # at_time: fire at exact event time
    jobs.append(("at_time", event_dt))

    return jobs


def _make_job_id() -> str:
    return f"reminder_{uuid.uuid4().hex[:12]}"


def _reminder_text(job_type: str, event: dict) -> str:
    if job_type == "day_before":
        prefix = "Напоминание: завтра"
    elif job_type == "hour_before":
        prefix = "Напоминание: через час"
    elif job_type == "at_time":
        prefix = "Напоминание: время события наступило"
    else:
        prefix = "Напоминание"

    lines = [f"{prefix}"]
    # Format date as DD.MM.YYYY HH:MM
    event_dt = datetime.fromisoformat(event['event_dt'])
    dt_formatted = event_dt.strftime("%d.%m.%Y %H:%M")
    lines.append(f"Когда: {dt_formatted}")
    lines.append(f"Активность: {event['activity']}")
    return "\n".join(lines)


def _build_reminder_keyboard(event_id: int, snooze_count: int):
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    buttons = []
    if snooze_count < 25:
        buttons.append(
            InlineKeyboardButton(
                text="Отложить на 1 час",
                callback_data=f"snooze:{event_id}",
            )
        )
    buttons.append(
        InlineKeyboardButton(
            text="Завершить",
            callback_data=f"done:{event_id}",
        )
    )
    return InlineKeyboardMarkup(inline_keyboard=[buttons])


async def _send_reminder(event_id: int, job_type: str) -> None:
    event = await database.get_event(event_id, path=_db_path)
    if not event or event["status"] != "active":
        return
    text = _reminder_text(job_type, event)
    kb = _build_reminder_keyboard(event_id, event["snooze_count"])
    try:
        await _bot.send_message(
            chat_id=event["user_id"],
            text=text,
            reply_markup=kb,
        )
    except Exception:
        logger.exception("Failed to send reminder for event %d", event_id)


async def schedule_event_jobs(event_id: int, event_dt: datetime, user_id: int, now: datetime | None = None) -> None:
    """Schedule all reminder jobs for an event."""
    if now is None:
        now = datetime.now(event_dt.tzinfo)

    job_specs = compute_job_times(event_dt, now)

    for job_type, run_dt in job_specs:
        job_id = _make_job_id()
        scheduler.add_job(
            _send_reminder,
            "date",
            run_date=run_dt,
            args=[event_id, job_type],
            id=job_id,
        )
        await database.create_job(
            event_id=event_id,
            job_type=job_type,
            run_dt=run_dt.isoformat(),
            scheduler_job_id=job_id,
            path=_db_path,
        )
        logger.info("Scheduled %s for event %d at %s (job %s)", job_type, event_id, run_dt, job_id)


async def schedule_snooze(event_id: int) -> datetime | None:
    """Snooze by +1 hour in user TZ by rescheduling the event timeline."""
    event = await database.get_event(event_id, path=_db_path)
    if not event or event["status"] != "active":
        return None
    if event["snooze_count"] >= 25:
        return None

    new_count = await database.increment_snooze(event_id, path=_db_path)
    if new_count > 25:
        return None

    user = await database.get_user(event["user_id"], path=_db_path)
    tz = ZoneInfo(user["timezone"]) if user else ZoneInfo("Europe/Moscow")
    now = datetime.now(tz)
    new_dt = now + timedelta(hours=1)

    await database.update_event_datetime(event_id, new_dt.isoformat(), path=_db_path)
    await cancel_event_jobs(event_id)
    await schedule_event_jobs(event_id, new_dt, event["user_id"], now=now)

    logger.info("Snoozed event %d (count=%d), rescheduled to %s", event_id, new_count, new_dt)
    return new_dt


async def cancel_event_jobs(event_id: int) -> None:
    job_ids = await database.delete_jobs_for_event(event_id, path=_db_path)
    for jid in job_ids:
        try:
            scheduler.remove_job(jid)
        except Exception:
            pass


async def restore_jobs_on_startup() -> None:
    """Re-create scheduler jobs from DB for active events after restart."""
    all_jobs = await database.get_all_jobs(path=_db_path)
    now = datetime.now(ZoneInfo("UTC"))

    for job in all_jobs:
        run_dt = datetime.fromisoformat(job["run_dt"])
        if run_dt.tzinfo is None:
            run_dt = run_dt.replace(tzinfo=ZoneInfo("UTC"))
        if run_dt <= now:
            continue
        try:
            scheduler.add_job(
                _send_reminder,
                "date",
                run_date=run_dt,
                args=[job["event_id"], job["job_type"]],
                id=job["scheduler_job_id"],
            )
            logger.info(
                "Restored job %s for event %d at %s",
                job["scheduler_job_id"],
                job["event_id"],
                run_dt,
            )
        except Exception:
            logger.exception("Failed to restore job %s", job["scheduler_job_id"])
