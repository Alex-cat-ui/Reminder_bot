"""Best-effort metric increment helpers."""

from __future__ import annotations

import db as database


async def bump_metric(key: str) -> None:
    try:
        await database.increment_metric(key)
    except Exception:
        # Metrics must not block core user flow.
        return
