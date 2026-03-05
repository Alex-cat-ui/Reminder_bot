"""Phase E: deterministic UX coverage for V2 flows."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest
from aiogram.types import InlineKeyboardMarkup

import handlers.event_edit as event_edit
import handlers.task_browser as browser
import handlers.wizard as wizard
from handlers.texts import MSG_PICK_DATE_WITH_BUTTONS, MSG_PICK_TIME_WITH_BUTTONS, MSG_TIME_PAST


class _FakeState:
    def __init__(self, data: dict | None = None):
        self.data = dict(data or {})
        self.current_state = None

    async def get_data(self):
        return dict(self.data)

    async def update_data(self, **kwargs):
        self.data.update(kwargs)

    async def set_state(self, state):
        self.current_state = state

    async def clear(self):
        self.data.clear()
        self.current_state = None


class _FakeMessage:
    def __init__(self):
        self.chat = SimpleNamespace(id=7001)
        self.answers: list[tuple[str, object | None]] = []
        self.edits: list[tuple[str, object | None]] = []
        self.bot = None
        self.message_id = 500

    async def answer(self, text, reply_markup=None):
        self.answers.append((text, reply_markup))
        return SimpleNamespace(message_id=self.message_id + len(self.answers))

    async def edit_text(self, text, reply_markup=None):
        self.edits.append((text, reply_markup))

    async def edit_reply_markup(self, reply_markup=None):
        return None


class _FakeCallback:
    def __init__(self, data: str, user_id: int = 111):
        self.data = data
        self.from_user = SimpleNamespace(id=user_id)
        self.message = _FakeMessage()
        self.answers: list[tuple[str | None, bool]] = []

    async def answer(self, text=None, show_alert=False):
        self.answers.append((text, show_alert))


@pytest.mark.asyncio
async def test_browser_return_restores_same_filter_and_page(monkeypatch):
    state = _FakeState(
        {
            "return_to_browser": True,
            "browser_sid": "abcdef12",
            "browser_filter": "tomorrow",
            "browser_page": 3,
            "browser_timezone": "Europe/Moscow",
            "browser_message_id": 900,
        }
    )
    message = _FakeMessage()
    edits = {}

    class _FakeBot:
        async def edit_message_text(self, *, text, chat_id, message_id, reply_markup):
            edits["text"] = text
            edits["chat_id"] = chat_id
            edits["message_id"] = message_id
            edits["reply_markup"] = reply_markup

    async def _build(**kwargs):
        return "BROWSER", InlineKeyboardMarkup(inline_keyboard=[]), kwargs["page"], 9

    message.bot = _FakeBot()
    monkeypatch.setattr(browser, "_build_browser_payload", _build)

    restored = await browser.return_to_browser_context(message, state, user_id=111, notice_text="OK")

    assert restored is True
    assert edits["message_id"] == 900
    assert edits["chat_id"] == 7001
    assert state.current_state == browser.BrowserStates.viewing
    assert state.data["browser_filter"] == "tomorrow"
    assert state.data["browser_page"] == 3
    assert message.answers[-1][0] == "OK"


@pytest.mark.asyncio
async def test_duplicate_cancel_returns_expected_screen_create(monkeypatch):
    state = _FakeState({"create_dup_sid": "abcdef12", "event_dt": "2026-03-10T10:00:00+03:00", "activity": "A"})
    cb = _FakeCallback("dup2:abcdef12:cancel")
    called = {"show": False}

    async def _show(message, data):
        called["show"] = True
        assert data.get("create_dup_sid") is None

    monkeypatch.setattr(wizard, "_show_confirmation", _show)
    await wizard.on_create_duplicate_decision(cb, state)

    assert called["show"] is True


@pytest.mark.asyncio
async def test_duplicate_cancel_returns_expected_screen_edit(monkeypatch):
    state = _FakeState(
        {
            "edit_dup_sid": "abcdef12",
            "edit_event_id": 10,
            "edit_timezone": "Europe/Moscow",
        }
    )
    cb = _FakeCallback("dup2:abcdef12:cancel")
    called = {"field_menu": None}

    async def _show_field_menu(message, state_obj, event_id, tz_name):
        called["field_menu"] = (event_id, tz_name)

    monkeypatch.setattr(event_edit, "_show_field_menu", _show_field_menu)
    await event_edit.on_edit_duplicate_decision(cb, state)

    assert called["field_menu"] == (10, "Europe/Moscow")


@pytest.mark.asyncio
async def test_duplicate_cancel_returns_expected_screen_clone():
    state = _FakeState(
        {
            "clone_dup_sid": "abcdef12",
            "clone_event_dt_iso": "2026-03-10T10:00:00+03:00",
            "clone_timezone": "Europe/Moscow",
            "clone_activity": "A",
            "clone_sid": "1234abcd",
            "clone_source_event_id": 77,
        }
    )
    cb = _FakeCallback("dup2:abcdef12:cancel")
    await browser.on_clone_duplicate_decision(cb, state)

    assert cb.message.answers
    assert "Активность: A" in cb.message.answers[-1][0]


@pytest.mark.asyncio
async def test_time_picker_callbacks_mutate_hh_mm(monkeypatch):
    state = _FakeState(
        {
            "tp_sid": "abcdef12",
            "timezone": "Europe/Moscow",
            "tp_hour": 14,
            "tp_minute": 35,
            "cal_session_id": "feedbeef",
        }
    )
    cb = _FakeCallback("tmr2:abcdef12:h:plus1")
    monkeypatch.setattr(wizard, "is_debounced", lambda _user_id: False)

    await wizard.on_create_time_picker(cb, state)
    assert state.data["tp_hour"] == 15
    assert state.data["tp_minute"] == 35

    cb2 = _FakeCallback("tmr2:abcdef12:m:set:45")
    cb2.message = cb.message
    await wizard.on_create_time_picker(cb2, state)
    assert state.data["tp_hour"] == 15
    assert state.data["tp_minute"] == 45


@pytest.mark.asyncio
async def test_picker_done_rejects_past_datetime(monkeypatch):
    class _FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):  # noqa: D401
            return cls(2026, 3, 4, 10, 0, tzinfo=tz)

    monkeypatch.setattr(wizard, "datetime", _FixedDateTime)
    state = _FakeState({"selected_date_iso": "2026-03-04"})

    ok, error = await wizard._apply_selected_time(state, "Europe/Moscow", 9, 59)

    assert ok is False
    assert error == MSG_TIME_PAST


@pytest.mark.asyncio
async def test_date_time_text_fallbacks_return_button_guidance():
    state = _FakeState()

    msg1 = _FakeMessage()
    await wizard.waiting_calendar_date_text_fallback(msg1)
    assert msg1.answers[-1][0] == MSG_PICK_DATE_WITH_BUTTONS

    msg2 = _FakeMessage()
    await wizard.process_time_after_calendar(msg2, state)
    assert msg2.answers[-1][0] == MSG_PICK_TIME_WITH_BUTTONS

    msg3 = _FakeMessage()
    await event_edit.waiting_edit_calendar_date_text_fallback(msg3)
    assert msg3.answers[-1][0] == MSG_PICK_DATE_WITH_BUTTONS

    msg4 = _FakeMessage()
    await event_edit.process_edit_time_manual(msg4, state)
    assert msg4.answers[-1][0] == MSG_PICK_TIME_WITH_BUTTONS

    msg5 = _FakeMessage()
    await browser.clone_waiting_date_manual(msg5)
    assert msg5.answers[-1][0] == MSG_PICK_DATE_WITH_BUTTONS

    msg6 = _FakeMessage()
    await browser.clone_time_manual(msg6, state)
    assert msg6.answers[-1][0] == MSG_PICK_TIME_WITH_BUTTONS


@pytest.mark.asyncio
async def test_calendar_step_header_not_duplicated_in_create_edit_clone():
    create_state = _FakeState()
    create_msg = _FakeMessage()
    await wizard._start_calendar_step(create_msg, create_state, "Europe/Moscow")
    assert len(create_msg.answers) == 1

    edit_state = _FakeState()
    edit_msg = _FakeMessage()
    await event_edit._start_edit_calendar_step(edit_msg, edit_state, event_id=10, tz_name="Europe/Moscow")
    assert len(edit_msg.answers) == 1

    clone_state = _FakeState()
    clone_msg = _FakeMessage()
    await browser._start_clone_calendar_step(
        clone_msg,
        clone_state,
        user_id=111,
        source_event={"id": 20, "activity": "Run"},
        tz_name="Europe/Moscow",
    )
    assert len(clone_msg.answers) == 1
