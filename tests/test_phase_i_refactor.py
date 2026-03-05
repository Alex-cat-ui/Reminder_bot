"""Phase I shared-helper and picker-path consistency tests."""

from __future__ import annotations

import pytest

import handlers.event_edit as event_edit
import handlers.task_browser as browser
import handlers.wizard as wizard
from handlers.texts import MSG_DEBOUNCE, MSG_STALE_CALENDAR
from handlers.time_picker import apply_picker_action
from handlers.ui_common import format_step_with_tz, format_time_picker_text


class _State:
    async def get_data(self):
        return {}


class _Callback:
    def __init__(self, data: str, user_id: int = 111):
        self.data = data
        self.from_user = type("User", (), {"id": user_id})()
        self.message = None
        self.answers: list[tuple[str | None, bool]] = []

    async def answer(self, text=None, show_alert=False):
        self.answers.append((text, show_alert))


def test_ui_common_step_and_picker_format():
    step = format_step_with_tz("Создание | Шаг 1/3", "Europe/Moscow")
    assert step == "Создание | Шаг 1/3\n"

    picker = format_time_picker_text("Создание | Шаг 2/3", "Europe/Moscow", 14, 35)
    assert "Создание | Шаг 2/3" in picker
    assert "Часовой пояс" not in picker
    assert "Текущее значение: 14:35" in picker


def test_apply_picker_action_shared_logic():
    h, m = apply_picker_action(14, 35, "t", "0900", tz_name="Europe/Moscow")
    assert (h, m) == (9, 0)

    h2, m2 = apply_picker_action(14, 35, "m", "set", tz_name="Europe/Moscow")
    assert (h2, m2) == (14, 35)


@pytest.mark.asyncio
async def test_picker_debounce_is_consistent_across_create_edit_clone(monkeypatch):
    cb_create = _Callback("tmr2:abcdef12:h:plus1")
    cb_edit = _Callback("tmr2:abcdef12:h:plus1")
    cb_clone = _Callback("tmr2:abcdef12:h:plus1")
    state = _State()

    monkeypatch.setattr(wizard, "is_debounced", lambda _uid: True)
    monkeypatch.setattr(event_edit, "is_debounced", lambda _uid: True)
    monkeypatch.setattr(browser, "is_debounced", lambda _uid: True)

    await wizard.on_create_time_picker(cb_create, state)
    await event_edit.on_edit_time_picker(cb_edit, state)
    await browser.on_clone_time_picker(cb_clone, state)

    assert cb_create.answers[-1] == (MSG_DEBOUNCE, False)
    assert cb_edit.answers[-1] == (MSG_DEBOUNCE, False)
    assert cb_clone.answers[-1] == (MSG_DEBOUNCE, False)


@pytest.mark.asyncio
async def test_picker_stale_session_is_consistent_across_create_edit_clone(monkeypatch):
    cb_create = _Callback("tmr2:abcdef12:h:plus1")
    cb_edit = _Callback("tmr2:abcdef12:h:plus1")
    cb_clone = _Callback("tmr2:abcdef12:h:plus1")
    state = _State()

    monkeypatch.setattr(wizard, "is_debounced", lambda _uid: False)
    monkeypatch.setattr(event_edit, "is_debounced", lambda _uid: False)
    monkeypatch.setattr(browser, "is_debounced", lambda _uid: False)

    await wizard.on_create_time_picker(cb_create, state)
    await event_edit.on_edit_time_picker(cb_edit, state)
    await browser.on_clone_time_picker(cb_clone, state)

    assert cb_create.answers[-1] == (MSG_STALE_CALENDAR, False)
    assert cb_edit.answers[-1] == (MSG_STALE_CALENDAR, False)
    assert cb_clone.answers[-1] == (MSG_STALE_CALENDAR, False)
