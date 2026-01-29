"""Tests for notes formatting."""

from notes_fmt import format_notes


class TestFormatNotes:
    def test_dash_returns_none(self):
        assert format_notes("-") is None

    def test_dash_with_spaces(self):
        assert format_notes("  -  ") is None

    def test_plain_text(self):
        assert format_notes("some note") == "some note"

    def test_comma_separated(self):
        result = format_notes("пункт 1, пункт 2, пункт 3")
        assert result == "— пункт 1\n— пункт 2\n— пункт 3"

    def test_comma_with_spaces(self):
        result = format_notes("  a , b , c  ")
        assert result == "— a\n— b\n— c"

    def test_empty_parts_filtered(self):
        result = format_notes("a,,b")
        assert result == "— a\n— b"

    def test_single_item_no_comma(self):
        result = format_notes("just one")
        assert result == "just one"
