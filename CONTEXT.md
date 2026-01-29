# Reminder Bot — Project Context

**Version 1.02** | Updated: 2026-01-29

## What this project is
Telegram reminder bot written in Python (aiogram).
Deterministic logic, NO LLM usage.

## Core features
- Create reminders via Telegram wizard
- Free-text date/time parsing in Russian (supports minutes)
- Timezone per user
- Reminders:
  - day_before at 12:00
  - hour_before
  - soon if < 60 minutes
  - at_time (exact event time)
- Inline actions:
  - Snooze (+1 hour, max 25)
  - Done (marks event done, cancels all jobs)
- Messages are NOT deleted, only inline buttons removed

## Technical stack
- Python 3.11+
- aiogram 3.x
- SQLite
- APScheduler
- pytest

## Important rules (must not break)
- No LLM
- Deterministic date parsing
- Events in the past are forbidden
- Snooze limit = 25
- Tests must be green

## Known issues / TODO
- Minor parsing edge cases may exist
- Needs polishing UX text

## Project structure
```
reminder_bot/
├── main.py              # Entry point
├── config.py            # Configuration (token, paths)
├── db.py                # SQLite layer (aiosqlite)
├── date_parser.py       # Russian date/time parsing
├── scheduler.py         # APScheduler jobs management
├── notes_fmt.py         # Notes formatting (comma → list)
├── handlers/
│   ├── __init__.py      # Router aggregation
│   ├── start.py         # /start command, main menu
│   ├── wizard.py        # FSM for creating reminders
│   ├── timezone.py      # /tz command
│   ├── weekly.py        # /week command
│   └── callbacks.py     # Inline button handlers
└── tests/
    ├── test_date_parser.py
    ├── test_db.py
    ├── test_scheduler.py
    ├── test_notes.py
    └── test_weekly.py
```

## Database schema
- **users**: user_id, timezone, created_at
- **events**: id, user_id, event_dt, activity, notes, status, snooze_count
- **jobs**: id, event_id, job_type, run_dt, scheduler_job_id

## Current state (v1.02)
- All core features implemented and working
- 107 tests passing
- Bot is production-ready for basic usage
- Jobs persist and restore on restart

## Changelog

### v1.02 (2026-01-29)
- Added "через минуту" / "через минутку" parsing
- Fixed "через N минуты" / "через N мин" for all minute forms
- Added word-based minute parsing: "через две минуты", "через пять минут", etc.
- Supported numerals: одну, две, три, пять, десять, пятнадцать, двадцать, тридцать, сорок, пятьдесят

### v1.01 (2026-01-29)
- Fixed date format in reminders: now shows "DD.MM.YYYY HH:MM"
- Improved past date validation: separate messages for date/time errors
- Added parsing for "через полчаса", "через полтора часа"
- Improved "через N мин" / "через N минут" parsing
- Fixed snooze button: now shows new reminder time in message

## How to run
- Set TELEGRAM_BOT_TOKEN in env or .env
- python main.py
- pytest -q
