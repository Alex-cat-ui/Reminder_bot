"""Duplicate-detection helpers."""

from __future__ import annotations

import re

import db as database


def normalize_activity(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


async def has_duplicate_event(
    *,
    user_id: int,
    event_dt_iso: str,
    activity: str,
    exclude_event_id: int | None = None,
) -> bool:
    activity_norm = normalize_activity(activity)
    rows = await database.find_duplicate_events(
        user_id,
        event_dt_iso,
        activity_norm,
        exclude_event_id=exclude_event_id,
    )
    return len(rows) > 0
