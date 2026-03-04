"""Phase 7 tests: admin metrics command."""

from __future__ import annotations

import pytest

import handlers.metrics as metrics_mod


class _FakeUser:
    def __init__(self, user_id: int):
        self.id = user_id


class _FakeMessage:
    def __init__(self, user_id: int):
        self.from_user = _FakeUser(user_id)
        self.answers = []

    async def answer(self, text, reply_markup=None):
        self.answers.append((text, reply_markup))


@pytest.mark.asyncio
async def test_metrics_today_non_admin_denied(monkeypatch):
    msg = _FakeMessage(999)
    monkeypatch.setattr(metrics_mod, "ADMIN_USER_IDS", {111})

    await metrics_mod.metrics_today(msg)

    assert msg.answers[-1][0] == "Доступ запрещен."


@pytest.mark.asyncio
async def test_metrics_today_admin_success(monkeypatch):
    msg = _FakeMessage(111)
    monkeypatch.setattr(metrics_mod, "ADMIN_USER_IDS", {111})

    async def _get_metrics(day_utc):
        return [
            {"key": "create_success", "value": 3},
            {"key": "delete_performed", "value": 1},
        ]

    monkeypatch.setattr(metrics_mod.database, "get_metrics_for_day", _get_metrics)

    await metrics_mod.metrics_today(msg)

    response = msg.answers[-1][0]
    assert "Метрики за " in response
    assert "create_success: 3" in response
    assert "delete_performed: 1" in response
