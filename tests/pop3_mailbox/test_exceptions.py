"""Auto-generated test module."""

import datetime
import poplib
from unittest.mock import MagicMock, patch

import pytest

from pop3_mailbox import Tools


class TestPOP3ListEmailsExceptions:
    """Test list_emails exception handlers (lines 224-227)."""

    @pytest.mark.asyncio
    async def test_list_emails_error_proto(self):
        """Test list_emails outer error_proto handler catches server-level errors (line 224)."""

        t = Tools()
        t.valves.username = "user"
        t.valves.password = "pass"
        t.valves.pop3_server = "pop3.example.com"

        mock_server = MagicMock()
        # error_proto on stat is caught by outer except → line 224
        mock_server.stat.side_effect = poplib.error_proto("BAD command on stat")
        mock_server.quit.return_value = None

        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await t.list_emails(count=5)
        assert "POP3 Error" in result

    @pytest.mark.asyncio
    async def test_list_emails_generic_exception(self):
        """Test list_emails catches generic Exception (line 226-227)."""
        t = Tools()
        t.valves.username = "user"
        t.valves.password = "pass"
        t.valves.pop3_server = "pop3.example.com"

        mock_server = MagicMock()
        mock_server.stat.side_effect = RuntimeError("connection reset")
        mock_server.quit.return_value = None

        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await t.list_emails(count=5)
        assert "Error" in result or "connection reset" in result


class TestPOP3ReadGenericException:
    """Test read_email generic exception handler (line 271)."""

    @pytest.mark.asyncio
    async def test_read_email_generic_exception(self):
        """Test read_email catches non-error_proto generic exception (line 271)."""
        t = Tools()
        t.valves.username = "user"
        t.valves.password = "pass"
        t.valves.pop3_server = "pop3.example.com"

        mock_server = MagicMock()
        mock_server.stat.return_value = (1, 500)
        mock_server.retr.side_effect = AttributeError("broken connection")
        mock_server.quit.return_value = None

        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await t.read_email(email_index=1)
        assert "error" in result.lower() and "broken connection" in result


class TestIsInDateRange:
    """Test _is_in_date_range helper method (lines 85, 87, 90)."""

    @pytest.fixture
    def tools(self):
        t = Tools()
        t.valves.pop3_server = "mail.example.com"
        return t

    def test_is_in_date_range_no_date(self, tools):
        """Test _is_in_date_range returns True when parsed_date is falsy (line 85)."""
        result = tools._is_in_date_range(None, datetime.datetime(2025, 1, 1), datetime.datetime(2025, 12, 31))
        assert result is True

    def test_is_in_date_range_no_filters(self, tools):
        """Test _is_in_date_range returns True when no date filters are set (line 87)."""
        result = tools._is_in_date_range("Sat, 15 Mar 2025 10:00:00 +0000", None, None)
        assert result is True

    def test_is_in_date_range_in_range(self, tools):
        """Test _is_in_date_range returns True when date is in range (line 90)."""
        after = datetime.datetime(2025, 1, 1)
        before = datetime.datetime(2026, 1, 1)
        result = tools._is_in_date_range("Sat, 15 Mar 2025 10:00:00 +0000", after, before)
        assert result is True

    def test_is_in_date_range_out_of_range_before(self, tools):
        """Test _is_in_date_range returns False when date is before filter."""
        after = datetime.datetime(2026, 1, 1)
        result = tools._is_in_date_range("Sat, 15 Mar 2025 10:00:00 +0000", after, None)
        assert result is False

    def test_is_in_date_range_out_of_range_after(self, tools):
        """Test _is_in_date_range returns False when date is after filter."""
        before = datetime.datetime(2024, 1, 1)
        result = tools._is_in_date_range("Sat, 15 Mar 2025 10:00:00 +0000", None, before)
        assert result is False

    def test_is_in_date_range_invalid_date_parsing(self, tools):
        """Test _is_in_date_range returns False when date can't be parsed."""
        result = tools._is_in_date_range(
            "not-a-valid-date", datetime.datetime(2025, 1, 1), datetime.datetime(2026, 1, 1)
        )
        assert result is False
