"""Shared UI labels and styling tokens."""

from __future__ import annotations

CANCEL_TEXT = "Отмена"
DONE_TEXT = "Готово"

STYLE_DANGER = "danger"
STYLE_SUCCESS = "success"
STYLE_PRIMARY = "primary"

CANCEL_TEXTS = frozenset({"Отмена", "🟥 Отмена", "🔴 Отмена"})


def is_cancel_text(value: str | None) -> bool:
    return (value or "").strip() in CANCEL_TEXTS
