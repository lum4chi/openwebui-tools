"""Tests for the _quote() helper that handles IMAP string literal escaping."""

from pydantic import Field

from imap_mailbox import _quote


class TestQuote:
    """Verify _quote() escapes backslashes, double-quotes and wraps in double-quotes."""

    def test_simple_no_special_chars(self):
        assert _quote("INBOX") == '"INBOX"'
        assert _quote("Sent") == '"Sent"'

    def test_space(self):
        assert _quote("Servizi Pubblici") == '"Servizi Pubblici"'

    def test_multiple_spaces(self):
        assert _quote("Folder With Many Words") == '"Folder With Many Words"'

    def test_backslash(self):
        assert _quote("back\\slash") == '"back\\\\slash"'

    def test_double_quote(self):
        assert _quote('say"hello"') == '"say\\"hello\\""'

    def test_backslash_and_quote(self):
        assert _quote(r"test\"quote") == '"test\\\\\\"quote"'

    def test_slash_separator(self):
        assert _quote("Gmail/All Mail") == '"Gmail/All Mail"'

    def test_unicode(self):
        assert _quote("Archivio 2025") == '"Archivio 2025"'

    def test_empty_string(self):
        assert _quote("") == '""'

    def test_already_has_quotes(self):
        assert _quote('"Already Quoted"') == '"\\"Already Quoted\\""'

    def test_numeric_folder(self):
        assert _quote("123") == '"123"'

    def test_quote_fieldinfo_with_string_default(self):
        from pydantic.fields import FieldInfo

        field = Field(default="TestFolder")
        assert isinstance(field, FieldInfo)
        assert _quote(field) == '"TestFolder"'

    def test_quote_fieldinfo_none_default(self):
        from pydantic.fields import FieldInfo

        field = Field(default=None)
        assert isinstance(field, FieldInfo)
        result = _quote(field)
        assert result is None

    def test_quote_none_input(self):
        assert _quote(None) is None
