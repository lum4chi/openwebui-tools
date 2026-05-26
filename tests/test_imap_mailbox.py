"""
Tests for the IMAP Mailbox Reader tool.
Uses mocked IMAP responses so no real server is required.
"""

import os
import sys
from collections.abc import Callable
from email.mime.text import MIMEText
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from imap_mailbox import Tools

try:
    from imaplib import IMAP4Exception as IMAP4Error
except ImportError:
    IMAP4Error = Exception  # type: ignore[misc,assignment]


def _make_raw_email(from_addr: str, to_addr: str, subject: str, body: str) -> bytes:
    """Create a raw email bytes object for mocking."""
    msg = MIMEText(body, "plain")
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg["Date"] = "Mon, 21 Apr 2025 10:00:00 +0000"
    msg["Message-ID"] = f"<{subject.replace(' ', '')}@test.com>"
    return msg.as_bytes()


def _make_mock_email_data(raw_email: bytes, uid: str = "1") -> list:
    """Wrap raw email bytes in IMAP RFC822 fetch response format."""
    prefix = str(uid).encode() + b" (RFC822 {}]"
    return [prefix, raw_email]


def _make_mock_server(emails: list[tuple], uid_prefix: str = "", override_uid: Callable | None = None) -> MagicMock:
    """Create a mock IMAP server that returns the given emails."""
    mock_server = MagicMock()

    def uid_side_effect(cmd, criteria=None, *args, **kwargs):
        """Handle conn.uid() calls. IMAP lib: search stores criteria in args,
        fetch stores UID in criteria and RFC822 in args."""
        if override_uid is not None:
            return override_uid(cmd, criteria, *args, **kwargs)
        if cmd == "search":
            search_criteria = args[0] if args else criteria
            if search_criteria is None or "ALL" in search_criteria.upper():
                matching_uids = [uid for _, uid in emails]
                return ("OK", [" ".join(matching_uids).encode()])
            import email as _em

            from_val = None
            subject_val = None
            for part in search_criteria.split():
                lo = part.lower()
                if lo.startswith("from") and not lo.startswith("since"):
                    if '"' in part:
                        from_val = part.split('"')[1]
                    else:
                        pl = search_criteria.split()
                        idx = pl.index(part) + 1
                        if idx < len(pl):
                            from_val = pl[idx].strip('"')
                elif lo.startswith("subject"):
                    if '"' in part:
                        subject_val = part.split('"')[1]
                    else:
                        pl = search_criteria.split()
                        idx = pl.index(part) + 1
                        if idx < len(pl):
                            subject_val = pl[idx].strip('"')
            matching_uids = []
            for raw_bytes, uid in emails:
                try:
                    msg = _em.message_from_bytes(raw_bytes)
                    fh = (msg.get("From", "") or "").lower()
                    sh = (msg.get("Subject", "") or "").lower()
                    if from_val and from_val.lower() not in fh:
                        continue
                    if subject_val and subject_val.lower() not in sh:
                        continue
                except Exception:
                    pass
                matching_uids.append(uid)
            return ("OK", [" ".join(matching_uids).encode()])
        elif cmd == "fetch":
            target_uid = criteria
            if isinstance(target_uid, (list, tuple)):
                target_uid = target_uid[0]
            for raw_bytes, uid in emails:
                if uid == target_uid:
                    return ("OK", [_make_mock_email_data(raw_bytes, uid)])
            return ("OK", [b""])
        elif cmd == "store":
            return ("OK", [b"FLAGS (\\Deleted)"])
        return ("OK", [b""])

    mock_server.login.return_value = ("OK", [b"Login successful"])
    mock_server.select.return_value = ("OK", [b"0 Messages"])
    mock_server.uid.side_effect = uid_side_effect
    mock_server.logout.return_value = ("OK", [b"Logout successful"])
    mock_server.expunge.return_value = ("OK", [b"EXPUNGE"])
    mock_server.close.return_value = None

    return mock_server


@pytest.fixture
def tools():
    t = Tools()
    t.valves.imap_server = "mail.example.com"
    t.valves.imap_port = 993
    t.valves.username = "testuser"
    t.valves.password = "testpass"
    t.valves.use_ssl = True
    t.valves.timeout = 5
    t.valves.folder = "INBOX"
    return t


class TestIMAPMailboxTool:
    """Test suite for IMAP Mailbox Manager tool."""

    @pytest.mark.asyncio
    async def test_list_emails_no_credentials(self):
        """Test that list_emails returns error when credentials are missing."""
        t = Tools()
        result = await t.list_emails(count=5)
        assert "Error" in result and "credentials" in result

    @pytest.mark.asyncio
    async def test_list_emails_empty_mailbox(self, tools):
        """Test listing emails in an empty mailbox."""
        mock_server = _make_mock_server([])
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.list_emails(count=10)
        assert "empty" in result.lower() or "No emails" in result

    @pytest.mark.asyncio
    async def test_list_emails_with_messages(self, tools):
        """Test listing emails with actual messages."""
        raw1 = _make_raw_email("alice@example.com", "bob@example.com", "Hello", "Hi Bob, how are you?")
        raw2 = _make_raw_email(
            "carol@example.com", "bob@example.com", "Invoice #123", "Please find attached the invoice."
        )
        emails = [(raw1, "1"), (raw2, "2")]
        mock_server = _make_mock_server(emails)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.list_emails(count=10)
        assert "alice@example.com" in result
        assert "carol@example.com" in result
        assert "Hello" in result
        assert "Invoice #123" in result

    @pytest.mark.asyncio
    async def test_read_email(self, tools):
        """Test reading a specific email by index."""
        raw1 = _make_raw_email("alice@example.com", "bob@example.com", "Hello", "Hi Bob, how are you?")
        raw2 = _make_raw_email(
            "carol@example.com", "bob@example.com", "Invoice #123", "Please find attached the invoice."
        )
        emails = [(raw1, "1"), (raw2, "2")]
        mock_server = _make_mock_server(emails)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.read_email(email_index=1)
        # Index 1 = UID 2 = carol (highest UID = newest = index 1)
        assert "carol@example.com" in result
        assert "Invoice #123" in result
        assert "Please find attached" in result

    @pytest.mark.asyncio
    async def test_read_email_out_of_range(self, tools):
        """Test reading an email with an out-of-range index."""
        raw = _make_raw_email("test@example.com", "u@example.com", "Test", "Body")
        mock_server = _make_mock_server([(raw, "1")])
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.read_email(email_index=99)
        assert "out of range" in result.lower()

    @pytest.mark.asyncio
    async def test_search_emails_by_from(self, tools):
        """Test searching emails by sender."""
        raw1 = _make_raw_email("alice@example.com", "bob@example.com", "Hello", "Hi Bob.")
        raw2 = _make_raw_email("carol@example.com", "bob@example.com", "Invoice", "Please pay.")
        emails = [(raw1, "1"), (raw2, "2")]
        mock_server = _make_mock_server(emails)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.search_emails(query='from:"alice@example.com"', count=10)
        assert "alice@example.com" in result
        assert "1 email" in result.lower() or "1 message" in result.lower()

    @pytest.mark.asyncio
    async def test_search_emails_by_subject(self, tools):
        """Test searching emails by subject."""
        raw1 = _make_raw_email("alice@example.com", "bob@example.com", "Hello", "Hi Bob.")
        raw2 = _make_raw_email("carol@example.com", "bob@example.com", "Invoice #123", "Please pay.")
        emails = [(raw1, "1"), (raw2, "2")]
        mock_server = _make_mock_server(emails)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.search_emails(query='subject:"invoice"', count=10)
        assert "carol@example.com" in result
        assert "Invoice" in result

    @pytest.mark.asyncio
    async def test_search_emails_text_fallback(self, tools):
        """Test searching emails with unqualified text (client-side filter)."""
        raw1 = _make_raw_email("alice@example.com", "bob@example.com", "Hello", "Hi Bob.")
        raw2 = _make_raw_email("carol@example.com", "bob@example.com", "Invoice", "Please pay invoice for services.")
        emails = [(raw1, "1"), (raw2, "2")]
        mock_server = _make_mock_server(emails)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.search_emails(query="invoice", count=10)
        # Client-side search should find the email with invoice in body
        assert "carol@example.com" in result

    @pytest.mark.asyncio
    async def test_get_email_count(self, tools):
        """Test getting the total email count."""

        def override_uid(cmd, criteria=None, *args, **kwargs):
            if cmd == "search":
                return ("OK", [b"1 2 3"])
            return ("OK", [b""])

        mock_server = _make_mock_server([], override_uid=override_uid)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.get_email_count()
        assert "3" in result

    @pytest.mark.asyncio
    async def test_get_email_count_empty(self, tools):
        """Test getting the email count for an empty mailbox."""
        mock_server = _make_mock_server([])
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.get_email_count()
        assert "0" in result

    @pytest.mark.asyncio
    async def test_get_email_count_no_credentials(self):
        """Test that get_email_count returns error when credentials are missing."""
        t = Tools()
        result = await t.get_email_count()
        assert "Error" in result and "credentials" in result

    @pytest.mark.asyncio
    async def test_delete_email_success(self, tools):
        """Test deleting a specific email."""
        tools.valves.allow_delete_single = True
        raw1 = _make_raw_email("alice@example.com", "bob@example.com", "Hello", "Hi Bob.")
        raw2 = _make_raw_email("carol@example.com", "bob@example.com", "Invoice", "Please pay.")
        emails = [(raw1, "1"), (raw2, "2")]
        mock_server = _make_mock_server(emails)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.delete_email(email_index=1)
        assert "deleted successfully" in result

    @pytest.mark.asyncio
    async def test_delete_email_out_of_range(self, tools):
        """Test deleting an email with an out-of-range index."""
        tools.valves.allow_delete_single = True
        raw = _make_raw_email("test@example.com", "u@example.com", "Test", "Body")
        mock_server = _make_mock_server([(raw, "1")])
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.delete_email(email_index=99)
        assert "out of range" in result.lower()

    @pytest.mark.asyncio
    async def test_delete_email_invalid_index(self, tools):
        """Test deleting an email with an invalid index (0 or negative)."""
        tools.valves.allow_delete_single = True
        raw = _make_raw_email("test@example.com", "u@example.com", "Test", "Body")
        mock_server = _make_mock_server([(raw, "1")])
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.delete_email(email_index=0)
        assert "out of range" in result.lower()

    @pytest.mark.asyncio
    async def test_delete_all_emails_success(self, tools):
        """Test deleting all emails from mailbox."""
        tools.valves.allow_delete_all = True
        raw1 = _make_raw_email("alice@example.com", "bob@example.com", "Hello", "Hi Bob.")
        raw2 = _make_raw_email("carol@example.com", "bob@example.com", "Invoice", "Please pay.")
        raw3 = _make_raw_email("dave@example.com", "bob@example.com", "Meeting", "See you tomorrow.")
        emails = [(raw1, "1"), (raw2, "2"), (raw3, "3")]
        mock_server = _make_mock_server(emails)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.delete_all_emails()
        assert "deleted successfully" in result
        assert "3 email" in result
        delete_calls = [c for c in mock_server.uid.call_args_list if c[0][0] == "store"]
        assert len(delete_calls) == 3

    @pytest.mark.asyncio
    async def test_delete_all_emails_empty_mailbox(self, tools):
        """Test deleting all emails from an empty mailbox."""
        tools.valves.allow_delete_all = True
        mock_server = _make_mock_server([])
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.delete_all_emails()
        assert "already empty" in result.lower() or "No emails" in result

    @pytest.mark.asyncio
    async def test_delete_all_emails_no_credentials(self):
        """Test that delete_all_emails returns error when credentials are missing."""
        t = Tools()
        t.valves.allow_delete_all = True
        result = await t.delete_all_emails()
        assert "Error" in result and "credentials" in result

    @pytest.mark.asyncio
    async def test_decode_mime_header(self, tools):
        """Test MIME header decoding utility."""
        result = tools._decode_mime_header("Hello World")
        assert result == "Hello World"
        assert tools._decode_mime_header("") == ""
        assert tools._decode_mime_header(None) == ""

    @pytest.mark.asyncio
    async def test_parse_email_structure(self, tools):
        """Test email parsing produces correct structure."""
        raw = _make_raw_email(
            "test@example.com",
            "recipient@example.com",
            "Test Subject",
            "Test body content",
        )
        parsed = tools._parse_email(raw)
        assert "test@example.com" in parsed["from"]
        assert "Test Subject" in parsed["subject"]
        assert "Test body content" in parsed["body"]
        assert "has_attachments" in parsed
        assert "attachment_count" in parsed
        assert "headers" in parsed

    @pytest.mark.asyncio
    async def test_regression_full_email_parsed_not_first_line_only(self, tools):
        """Regression: verify the full email is parsed, not just the first line."""
        raw = _make_raw_email(
            "regression@test.com",
            "user@test.com",
            "Regression Test Subject",
            "This body text must appear in the output, proving the full email "
            "was parsed and not truncated to the first header line.",
        )
        emails = [(raw, "1")]
        mock_server = _make_mock_server(emails)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.read_email(email_index=1)
        assert "regression@test.com" in result
        assert "Regression Test Subject" in result
        assert "This body text must appear" in result

    @pytest.mark.asyncio
    async def test_connection_error(self, tools):
        """Test handling of IMAP connection errors."""
        mock_server = MagicMock()
        mock_server.login.side_effect = IMAP4Error("535 Authentication failed")
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.get_email_count()
        assert "IMAP Error" in result

    @pytest.mark.asyncio
    async def test_select_folder(self, tools):
        """Test that a custom folder name is used in IMAP select."""
        tools.valves.folder = "Sent"
        mock_server = _make_mock_server([])
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            await tools.get_email_count()
        mock_server.select.assert_called()
        call_args = mock_server.select.call_args
        assert call_args[0][0] == "Sent"

    @pytest.mark.asyncio
    async def test_delete_email_disabled_by_default(self, tools):
        """Test that delete_email is blocked when allow_delete_single is False (default)."""
        assert tools.valves.allow_delete_single is False
        result = await tools.delete_email(email_index=1)
        assert "disabled" in result.lower() and "allow_delete_single" in result

    @pytest.mark.asyncio
    async def test_delete_email_enabled(self, tools):
        """Test deleting a specific email when allow_delete_single is True."""
        tools.valves.allow_delete_single = True
        raw1 = _make_raw_email("alice@example.com", "bob@example.com", "Hello", "Hi Bob.")
        raw2 = _make_raw_email("carol@example.com", "bob@example.com", "Invoice", "Please pay.")
        emails = [(raw1, "1"), (raw2, "2")]
        mock_server = _make_mock_server(emails)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.delete_email(email_index=1)
        assert "deleted successfully" in result

    @pytest.mark.asyncio
    async def test_delete_all_emails_disabled_by_default(self, tools):
        """Test that delete_all_emails is blocked when allow_delete_all is False (default)."""
        assert tools.valves.allow_delete_all is False
        result = await tools.delete_all_emails()
        assert "disabled" in result.lower() and "allow_delete_all" in result

    @pytest.mark.asyncio
    async def test_delete_all_emails_enabled(self, tools):
        """Test deleting all emails when allow_delete_all is True."""
        tools.valves.allow_delete_all = True
        raw1 = _make_raw_email("alice@example.com", "bob@example.com", "Hello", "Hi Bob.")
        raw2 = _make_raw_email("carol@example.com", "bob@example.com", "Invoice", "Please pay.")
        raw3 = _make_raw_email("dave@example.com", "bob@example.com", "Meeting", "See you tomorrow.")
        emails = [(raw1, "1"), (raw2, "2"), (raw3, "3")]
        mock_server = _make_mock_server(emails)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.delete_all_emails()
        assert "deleted successfully" in result
        assert "3 email" in result

    @pytest.mark.asyncio
    async def test_default_toggles_are_off(self):
        """Test that delete toggles default to False."""
        t = Tools()
        assert t.valves.allow_delete_single is False
        assert t.valves.allow_delete_all is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
