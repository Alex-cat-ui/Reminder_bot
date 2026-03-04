"""Tests for canonical text catalog."""

import handlers.texts as t


def test_required_text_constants_exist():
    required = [
        "MSG_UNAUTHORIZED",
        "MSG_INVALID_ACTION",
        "MSG_STALE_CALENDAR",
        "MSG_CREATED",
        "MSG_UPDATED",
        "MSG_DELETED",
        "MSG_CREATION_CANCELLED",
        "MSG_TIME_PARSE_ERROR",
        "MSG_TIME_PAST",
        "MSG_ACTIVITY_LEN",
    ]
    for name in required:
        assert hasattr(t, name), f"missing constant: {name}"


def test_no_duplicate_conflicting_messages():
    # Critical security-related texts should remain distinct.
    assert t.MSG_INVALID_ACTION != t.MSG_UNAUTHORIZED
    assert t.MSG_STALE_CALENDAR != t.MSG_INVALID_ACTION
