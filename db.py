"""SQLite database layer (async via aiosqlite)."""

from __future__ import annotations

import aiosqlite
from datetime import datetime

DB_PATH: str = "bot.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    timezone TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    event_dt TEXT NOT NULL,
    activity TEXT NOT NULL,
    notes TEXT,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    snooze_count INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL,
    job_type TEXT NOT NULL,
    run_dt TEXT NOT NULL,
    scheduler_job_id TEXT NOT NULL,
    FOREIGN KEY (event_id) REFERENCES events(id)
);
"""


async def init_db(path: str = DB_PATH) -> None:
    async with aiosqlite.connect(path) as conn:
        await conn.executescript(SCHEMA)
        await conn.commit()


async def get_connection(path: str = DB_PATH) -> aiosqlite.Connection:
    conn = await aiosqlite.connect(path)
    conn.row_factory = aiosqlite.Row
    return conn


# ── Users ──────────────────────────────────────────

async def get_user(user_id: int, path: str = DB_PATH) -> dict | None:
    async with aiosqlite.connect(path) as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        row = await cur.fetchone()
        if row:
            return dict(row)
        return None


async def upsert_user(user_id: int, timezone: str, path: str = DB_PATH) -> None:
    async with aiosqlite.connect(path) as conn:
        await conn.execute(
            """INSERT INTO users (user_id, timezone, created_at)
               VALUES (?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET timezone = excluded.timezone""",
            (user_id, timezone, datetime.utcnow().isoformat()),
        )
        await conn.commit()


# ── Events ─────────────────────────────────────────

async def create_event(
    user_id: int,
    event_dt: str,
    activity: str,
    notes: str | None,
    path: str = DB_PATH,
) -> int:
    async with aiosqlite.connect(path) as conn:
        cur = await conn.execute(
            """INSERT INTO events (user_id, event_dt, activity, notes, created_at, status, snooze_count)
               VALUES (?, ?, ?, ?, ?, 'active', 0)""",
            (user_id, event_dt, activity, notes, datetime.utcnow().isoformat()),
        )
        await conn.commit()
        return cur.lastrowid  # type: ignore[return-value]


async def get_event(event_id: int, path: str = DB_PATH) -> dict | None:
    async with aiosqlite.connect(path) as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute("SELECT * FROM events WHERE id = ?", (event_id,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def update_event_status(event_id: int, status: str, path: str = DB_PATH) -> None:
    async with aiosqlite.connect(path) as conn:
        await conn.execute("UPDATE events SET status = ? WHERE id = ?", (status, event_id))
        await conn.commit()


async def increment_snooze(event_id: int, path: str = DB_PATH) -> int:
    async with aiosqlite.connect(path) as conn:
        conn.row_factory = aiosqlite.Row
        await conn.execute(
            "UPDATE events SET snooze_count = snooze_count + 1 WHERE id = ?", (event_id,)
        )
        await conn.commit()
        cur = await conn.execute("SELECT snooze_count FROM events WHERE id = ?", (event_id,))
        row = await cur.fetchone()
        return row["snooze_count"] if row else 0


async def get_week_events(user_id: int, start_dt: str, end_dt: str, path: str = DB_PATH) -> list[dict]:
    async with aiosqlite.connect(path) as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute(
            """SELECT * FROM events
               WHERE user_id = ? AND status = 'active'
                 AND event_dt >= ? AND event_dt <= ?
               ORDER BY event_dt""",
            (user_id, start_dt, end_dt),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def get_active_events(path: str = DB_PATH) -> list[dict]:
    async with aiosqlite.connect(path) as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute("SELECT * FROM events WHERE status = 'active'")
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


# ── Jobs ───────────────────────────────────────────

async def create_job(
    event_id: int,
    job_type: str,
    run_dt: str,
    scheduler_job_id: str,
    path: str = DB_PATH,
) -> int:
    async with aiosqlite.connect(path) as conn:
        cur = await conn.execute(
            """INSERT INTO jobs (event_id, job_type, run_dt, scheduler_job_id)
               VALUES (?, ?, ?, ?)""",
            (event_id, job_type, run_dt, scheduler_job_id),
        )
        await conn.commit()
        return cur.lastrowid  # type: ignore[return-value]


async def get_jobs_for_event(event_id: int, path: str = DB_PATH) -> list[dict]:
    async with aiosqlite.connect(path) as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute("SELECT * FROM jobs WHERE event_id = ?", (event_id,))
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def delete_jobs_for_event(event_id: int, path: str = DB_PATH) -> list[str]:
    """Delete all jobs for an event; return scheduler_job_ids for cancellation."""
    async with aiosqlite.connect(path) as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute("SELECT scheduler_job_id FROM jobs WHERE event_id = ?", (event_id,))
        rows = await cur.fetchall()
        job_ids = [r["scheduler_job_id"] for r in rows]
        await conn.execute("DELETE FROM jobs WHERE event_id = ?", (event_id,))
        await conn.commit()
        return job_ids


async def get_all_jobs(path: str = DB_PATH) -> list[dict]:
    async with aiosqlite.connect(path) as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute(
            """SELECT j.*, e.status as event_status
               FROM jobs j JOIN events e ON j.event_id = e.id
               WHERE e.status = 'active'"""
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]
