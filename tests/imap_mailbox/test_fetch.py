"""Auto-generated test module."""

from unittest.mock import MagicMock, patch

import pytest

from imap_mailbox import Tools

from .conftest import _make_raw_email


class TestFetchEmailsByUid:
    """Test _fetch_emails_by_uid method."""

    @pytest.mark.asyncio
    async def test_fetch_emails_by_uid_success(self):
        """Test _fetch_emails_by_uid returns parsed email dicts with UIDs."""
        t = Tools()
        t.valves.username = "u"
        t.valves.password = "p"
        t.valves.imap_server = "mail.example.com"
        mock_server = MagicMock()
        raw = _make_raw_email("a@b.com", "c@d.com", "Test", "Body")

        # The _fetch_emails_by_uid method calls conn.uid("fetch", uid, "(RFC822)")
        # and expects a tuple of (status, raw_data) where raw_data[0] is [prefix, email_bytes]
        mock_server.uid.return_value = ("OK", [[b"1 (RFC822 {}", raw]])

        result = t._fetch_emails_by_uid(mock_server, ["1"])
        assert len(result) == 1
        assert result[0]["from"] == "a@b.com"
        assert result[0]["uid"] == "1"

    @pytest.mark.asyncio
    async def test_fetch_emails_by_uid_empty_raw_data(self):
        """Test _fetch_emails_by_uid when raw_data is empty skips that UID."""
        t = Tools()
        mock_conn = MagicMock()
        mock_conn.uid.return_value = ("OK", [])
        result = t._fetch_emails_by_uid(mock_conn, ["1"])
        assert result == []

    @pytest.mark.asyncio
    async def test_fetch_emails_by_uid_connection_error(self):
        """Test _fetch_emails_by_uid skips UIDs that raise exceptions."""
        t = Tools()
        mock_conn = MagicMock()
        mock_conn.uid.side_effect = RuntimeError("connection lost")
        result = t._fetch_emails_by_uid(mock_conn, ["1"])
        assert result == []

    @pytest.mark.asyncio
    async def test_fetch_emails_by_uid_parse_error(self):
        """Test _fetch_emails_by_uid skips UIDs that fail parsing."""
        t = Tools()
        mock_conn = MagicMock()
        mock_conn.uid.return_value = ("OK", [[b"1 (RFC822 {}", b"fake"]])
        with patch.object(t, "_parse_email", side_effect=ValueError("parse failed")):
            result = t._fetch_emails_by_uid(mock_conn, ["1"])
        assert result == []

    @pytest.mark.asyncio
    async def test_fetch_emails_by_uid_multiple_uids(self):
        """Test _fetch_emails_by_uid fetches multiple UIDs."""
        t = Tools()
        t.valves.username = "u"
        t.valves.password = "p"
        t.valves.imap_server = "mail.example.com"
        mock_server = MagicMock()

        def uid_side_effect(cmd, criteria=None, *args, **kwargs):
            if cmd == "fetch":
                raw = _make_raw_email("a@b.com", "c@d.com", "Test", f"Body {criteria}")
                return ("OK", [[f"{criteria} (RFC822".encode(), raw]])
            return ("OK", [b""])

        mock_server.uid.side_effect = uid_side_effect

        result = t._fetch_emails_by_uid(mock_server, ["1", "2", "3"])
        assert len(result) == 3
        assert result[0]["uid"] == "1"
        assert result[1]["uid"] == "2"
        assert result[2]["uid"] == "3"


class TestNormalizeUids:
    """Test _normalize_uids helper method."""

    @pytest.mark.asyncio
    async def test_normalize_uids_single_string(self):
        """Test _normalize_uids with a plain string."""
        t = Tools()
        result = t._normalize_uids("1")
        assert result == ["1"]

    @pytest.mark.asyncio
    async def test_normalize_uids_list_of_strings(self):
        """Test _normalize_uids with a list of strings."""
        t = Tools()
        result = t._normalize_uids(["1", "2", "3"])
        assert result == ["1", "2", "3"]

    @pytest.mark.asyncio
    async def test_normalize_uids_comma_separated(self):
        """Test _normalize_uids with comma-separated string."""
        t = Tools()
        result = t._normalize_uids("1,2,3")
        assert result == ["1", "2", "3"]

    @pytest.mark.asyncio
    async def test_normalize_uids_none(self):
        """Test _normalize_uids with None returns empty list."""
        t = Tools()
        result = t._normalize_uids(None)
        assert result == []

    @pytest.mark.asyncio
    async def test_normalize_uids_empty_string(self):
        """Test _normalize_uids with empty string returns empty list."""
        t = Tools()
        result = t._normalize_uids("")
        assert result == []

    @pytest.mark.asyncio
    async def test_normalize_uids_empty_list(self):
        """Test _normalize_uids with empty list returns empty list."""
        t = Tools()
        result = t._normalize_uids([])
        assert result == []


class TestResolveFieldinfo:
    """Test _resolve_fieldinfo helper method."""

    @pytest.mark.asyncio
    async def test_resolve_fieldinfo_string(self):
        """Test _resolve_fieldinfo passes strings through."""
        t = Tools()
        result = t._resolve_fieldinfo("hello", "fallback")
        assert result == "hello"

    @pytest.mark.asyncio
    async def test_resolve_fieldinfo_int(self):
        """Test _resolve_fieldinfo passes ints through."""
        t = Tools()
        result = t._resolve_fieldinfo(42, "fallback")
        assert result == 42

    @pytest.mark.asyncio
    async def test_resolve_fieldinfo_list(self):
        """Test _resolve_fieldinfo passes lists through."""

        t = Tools()
        result = t._resolve_fieldinfo(["1", "2"], "fallback")
        assert result == ["1", "2"]

    @pytest.mark.asyncio
    async def test_resolve_fieldinfo_fieldinfo_with_default(self):
        """Test _resolve_fieldinfo extracts default from FieldInfo."""
        from pydantic import Field

        t = Tools()
        field = Field(default="test_value")
        result = t._resolve_fieldinfo(field, "fallback")
        assert result == "test_value"

    @pytest.mark.asyncio
    async def test_resolve_fieldinfo_fieldinfo_without_default(self):
        """Test _resolve_fieldinfo returns fallback when FieldInfo has no default."""
        from pydantic import Field

        t = Tools()
        # Field with only description, no default
        field = Field(description="Test field")
        result = t._resolve_fieldinfo(field, "fallback")
        assert result == "fallback"
