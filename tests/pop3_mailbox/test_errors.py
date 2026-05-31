"""Auto-generated test module."""

import poplib
from email.mime.text import MIMEText
from unittest.mock import MagicMock, patch

import pytest

from pop3_mailbox import Tools

from .conftest import (
    _make_mock_server,
)


class TestPOP3GenericErrorPaths:
    """Test generic exception handling in POP3 methods."""

    @pytest.mark.asyncio
    async def test_delete_email_generic_error(self):
        """Test delete_email catches generic exceptions (e.g., network)."""
        t = Tools()
        t.valves.pop3_server = "mail.test.com"
        t.valves.username = "user"
        t.valves.password = "pass"
        t.valves.allow_delete_single = True

        with patch("poplib.POP3_SSL", side_effect=OSError("connection refused")):
            result = await t.delete_email(email_index=1)
        assert "Error deleting" in result

    @pytest.mark.asyncio
    async def test_search_emails_generic_error(self):
        """Test search_emails catches generic exceptions."""
        t = Tools()
        t.valves.pop3_server = "mail.test.com"
        t.valves.username = "user"
        t.valves.password = "pass"

        with patch("poplib.POP3_SSL", side_effect=OSError("connection refused")):
            result = await t.search_emails(query="subject:test", count=10)
        assert "Error searching" in result

    @pytest.mark.asyncio
    async def test_get_email_count_generic_error(self):
        """Test get_email_count catches generic exceptions."""
        t = Tools()
        t.valves.pop3_server = "mail.test.com"
        t.valves.username = "user"
        t.valves.password = "pass"

        with patch("poplib.POP3_SSL", side_effect=OSError("connection refused")):
            result = await t.get_email_count()
        assert "Error checking mailbox" in result

    @pytest.mark.asyncio
    async def test_read_email_generic_error(self):
        """Test read_email catches generic exceptions."""
        t = Tools()
        t.valves.pop3_server = "mail.test.com"
        t.valves.username = "user"
        t.valves.password = "pass"

        with patch("poplib.POP3_SSL", side_effect=OSError("connection refused")):
            result = await t.read_email(email_index=1)
        assert "Error reading" in result


class TestPOP3GenericErrorProto:
    """Test error_proto handling in read_email and search_emails."""

    @pytest.mark.asyncio
    async def test_read_email_error_proto(self):
        """Test read_email catches poplib.error_proto during retr() (line 271)."""
        t = Tools()
        t.valves.username = "user"
        t.valves.password = "pass"
        t.valves.pop3_server = "pop3.example.com"

        mock_server = MagicMock()
        mock_server.stat.return_value = (1, 500)
        mock_server.retr.side_effect = poplib.error_proto("402 Message too big")
        mock_server.quit.return_value = None

        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await t.read_email(email_index=1)
        assert "POP3 Error" in result

    @pytest.mark.asyncio
    async def test_search_error_proto(self):
        """Test search_emails catches poplib.error_proto during stat() (line 373)."""
        t = Tools()
        t.valves.username = "user"
        t.valves.password = "pass"
        t.valves.pop3_server = "pop3.example.com"

        mock_server = MagicMock()
        mock_server.stat.side_effect = poplib.error_proto("BAD command on stat")
        mock_server.quit.return_value = None

        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await t.search_emails(query="test", count=10)
        assert "POP3 Error" in result


class TestPOP3InnerFetchException:
    """Test inner exception handler in list_emails."""

    @pytest.mark.asyncio
    async def test_list_emails_inner_fetch_error(self, tools):
        """Test list_emails handles individual retr() failures gracefully."""
        emails = [
            b"From: a@b.com\r\nTo: c@d.com\r\nSubject: OK\r\nDate: Mon, 21 Apr 2025 10:00:00 +0000\r\n\r\nBody",
            b"From: e@f.com\r\nTo: g@h.com\r\nSubject: OK2\r\nDate: Mon, 21 Apr 2025 11:00:00 +0000\r\n\r\nBody2",
        ]

        mock_server = MagicMock()
        mock_server.stat.return_value = (2, 2000)
        mock_server.quit.return_value = None

        call_count = [0]

        def mock_retr(index):
            call_count[0] += 1
            if call_count[0] <= 2 and 1 <= index <= 2:
                email_idx = index - 1
                if 0 <= email_idx < len(emails):
                    lines = emails[email_idx].split(b"\r\n")
                    return ("220 OK", lines, len(emails[email_idx]))
            return ("500 Error", [], 0)

        mock_server.retr.side_effect = mock_retr

        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await tools.list_emails(count=5)
        # Should show at least the successful email
        assert "Subject:" in result

    @pytest.mark.asyncio
    async def test_list_emails_inner_fetch_exception(self):
        """Test list_emails inner retr() exception handler (lines 191-192)."""
        t = Tools()
        t.valves.username = "user"
        t.valves.password = "pass"
        t.valves.pop3_server = "pop3.example.com"

        mock_server = MagicMock()
        mock_server.stat.return_value = (2, 2000)
        mock_server.quit.return_value = None

        call_order = []
        emails = [
            b"From: a@b.com\r\nTo: c@d.com\r\nSubject: OK1\r\nDate: Mon, 21 Apr 2025 10:00:00 +0000\r\n\r\nBody1",
            b"From: e@f.com\r\nTo: g@h.com\r\nSubject: OK2\r\nDate: Tue, 22 Apr 2025 11:00:00 +0000\r\n\r\nBody2",
        ]

        def mock_retr(index):
            call_order.append(index)
            if index == 1:
                raise RuntimeError("inner fetch error")
            if index == 2:
                lines = emails[1].split(b"\r\n")
                return ("220 OK", lines, len(emails[1]))
            raise poplib.error_proto("no message")

        mock_server.retr.side_effect = mock_retr

        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await t.list_emails(count=5)
        assert "OK2" in result or "Subject:" in result


class TestPOP3MIMECharsetFallback:
    """Test MIME decoding charset fallback paths."""

    @pytest.mark.asyncio
    async def test_parse_email_charset_fallback(self, tools):
        """Test _parse_email handles unknown charset fallback to UTF-8."""
        # Email with charset that will cause LookupError
        raw = b"""\
Subject: =?unknown-charset-xyz?b?dGVzdA==?=\r
From: from@example.com\r
To: to@example.com\r
Date: Mon, 21 Apr 2025 10:00:00 +0000\r
Content-Type: text/plain; charset=nonexistent-charset-abc\r
\r
test body"""

        mock_server = _make_mock_server(1, [raw])
        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await tools.list_emails(count=5)
        # Should not crash with charset error
        assert "Subject:" in result


class TestPOP3GetBodyMultipartException:
    """Test _get_email_body multipart decode exception path (lines 93-94)."""

    @pytest.mark.asyncio
    async def test_get_email_body_multipart_decode_error(self):
        """Test _get_email_body where multipart part triggers decode error (lines 93-94)."""
        import email.message as _email_msg

        class BadPart(MIMEText):
            def get_content_charset(self):
                return "nonexistent-charset-xyz-123"

            def get_payload(self, decode=False):
                if decode:
                    return b"\xff\xfe\x80\x81"  # Invalid bytes for any charset
                return "inner"

        t = Tools()
        msg = _email_msg.EmailMessage()
        msg["Content-Type"] = "multipart/mixed; boundary=outer"
        msg.set_payload([BadPart("inner text")])

        # The sub-part should trigger the except block at lines 93-94
        result = t._get_email_body(msg)
        # Should not crash and result should be a string
        assert isinstance(result, str)


class TestPOP3SearchGenericException:
    """Test search_emails generic exception (line 374, not 408 which is DELETE)."""

    @pytest.mark.asyncio
    async def test_search_emails_generic_exception(self):
        """Test search_emails with generic non-error_proto exception (line 374)."""
        t = Tools()
        t.valves.username = "user"
        t.valves.password = "pass"
        t.valves.pop3_server = "pop3.example.com"

        mock_server = MagicMock()
        mock_server.stat.return_value = (1, 500)
        mock_server.retr.side_effect = RuntimeError("broken pipe")
        mock_server.quit.return_value = None

        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await t.search_emails(query="test")
        assert "Error" in result or "No emails found" in result
