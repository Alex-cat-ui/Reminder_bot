"""Phase H UI consistency tests."""

from __future__ import annotations

from datetime import datetime

import pytest

import handlers.task_browser as browser
from handlers.texts import MSG_TIME_PAST
from handlers.time_picker import build_time_picker_kb


def test_time_past_error_is_actionable():
    assert "Выберите более позднее время кнопками" in MSG_TIME_PAST


def test_time_picker_contains_quick_presets_row():
    kb = build_time_picker_kb("abcdef12", 14, 35)
    row1 = kb.inline_keyboard[0]
    row2 = kb.inline_keyboard[1]
    row3 = kb.inline_keyboard[2]
    preset_row = kb.inline_keyboard[3]
    finish_row = kb.inline_keyboard[4]
    cancel_row = kb.inline_keyboard[5]

    assert [btn.style for btn in row1] == ["success", "success", "success"]
    assert [btn.style for btn in row2] == ["success", "success", "success"]
    assert [btn.style for btn in row3] == ["primary", "primary", "primary", "primary"]
    assert [btn.text for btn in preset_row] == ["09:00", "12:00", "18:00", "20:00"]
    assert [btn.style for btn in preset_row] == ["primary", "primary", "primary", "primary"]
    assert [btn.callback_data for btn in preset_row] == [
        "tmr2:abcdef12:t:set:0900",
        "tmr2:abcdef12:t:set:1200",
        "tmr2:abcdef12:t:set:1800",
        "tmr2:abcdef12:t:set:2000",
    ]
    assert finish_row[1].text == "Готово"
    assert finish_row[1].style == "success"
    assert cancel_row[0].text == "Отмена"
    assert cancel_row[0].style == "danger"


@pytest.mark.asyncio
async def test_browser_payload_has_no_tz_parenthesis_and_delete_row_separate(monkeypatch):
    async def _count(user_id, filter_name, start_dt, end_dt):
        return 1

    async def _list(user_id, filter_name, start_dt, end_dt, limit, offset):
        return [
            {
                "id": 10,
                "event_dt": datetime(2026, 3, 10, 18, 0).isoformat(),
                "activity": "Task",
            }
        ]

    monkeypatch.setattr(browser.database, "count_events_by_filter", _count)
    monkeypatch.setattr(browser.database, "list_events_by_filter", _list)

    text, kb, page, total_pages = await browser._build_browser_payload(
        user_id=111,
        tz_name="Europe/Moscow",
        sid="abcdef12",
        filter_name="all",
        page=1,
    )

    assert page == 1
    assert total_pages == 1
    assert "(Europe/Moscow)" not in text

    action_rows = [row for row in kb.inline_keyboard if any(btn.text and "#1" in btn.text for btn in row)]
    assert len(action_rows) == 2
    assert [btn.text for btn in action_rows[0]] == ["Изменить #1", "Повторить #1"]
    assert [btn.text for btn in action_rows[1]] == ["Удалить #1"]
