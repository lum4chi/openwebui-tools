"""
Tests for the IMAP Mailbox Reader tool.
Uses mocked IMAP responses so no real server is required.
"""

import email
import imaplib as _imaplib
import os
import sys
from collections.abc import Callable
from email.mime.text import MIMEText
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from imap_mailbox import EncryptionMode, Tools

_IMAP_EXCEPTION = getattr(_imaplib, "IMAP4Exception", Exception)


def _make_raw_email(from_addr: str, to_addr: str, subject: str, body: str) -> bytes:
    """Create a raw email bytes object for mocking."""
    msg = MIMEText(body, "plain")
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg["Date"] = "Mon, 21 Apr 2025 10:00:00 +0000"
    msg["Message-ID"] = f"<{subject.replace(' ', '')}@test.com>"
    return msg.as_bytes()


def _make_raw_email_with_attachment(from_addr: str, to_addr: str, subject: str, body: str) -> bytes:
    """Create a multipart email with one attachment for mocking."""
    from email.mime.base import MIMEBase
    from email.mime.multipart import MIMEMultipart

    msg = MIMEMultipart()
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg["Date"] = "Mon, 21 Apr 2025 10:00:00 +0000"
    msg["Message-ID"] = f"<{subject.replace(' ', '')}@test.com>"
    msg.attach(MIMEText(body, "plain"))
    part = MIMEBase("application", "octet-stream")
    part.set_payload(b"fake-attachment-content")
    part.add_header("Content-Disposition", "attachment", filename="document.pdf")
    msg.attach(part)
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
    t.valves.encryption_method = EncryptionMode.implicit
    t.valves.timeout = 5
    t.valves.inbox_folder = "INBOX"
    return t


class TestIMAPMailboxTool:
    """Test suite for IMAP Mailbox Manager tool."""

    @pytest.mark.asyncio
    async def test_list_inbox_emails_no_credentials(self):
        """Test that list_inbox_emails returns error when credentials are missing."""
        t = Tools()
        t.valves.allow_list_inbox = True
        result = await t.list_inbox_emails(count=5)
        assert "Error" in result and "credentials" in result

    @pytest.mark.asyncio
    async def test_list_emails_no_folder_required(self):
        """Test that list_emails requires a folder parameter."""
        t = Tools()
        t.valves.imap_server = "mail.example.com"
        t.valves.imap_port = 993
        t.valves.username = "testuser"
        t.valves.password = "testpass"
        with pytest.raises(TypeError):
            await t.list_emails(count=5)  # pyright: ignore

    @pytest.mark.asyncio
    async def test_list_emails_empty_mailbox(self, tools):
        """Test listing emails in an empty mailbox."""
        mock_server = _make_mock_server([])
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.list_emails(folder="INBOX", count=10)
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
            result = await tools.list_emails(folder="INBOX", count=10)
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
        mock_server.login.side_effect = _IMAP_EXCEPTION("535 Authentication failed")
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.get_email_count()
        assert "IMAP Error" in result

    @pytest.mark.asyncio
    async def test_select_inbox_folder(self, tools):
        """Test that a custom inbox folder name is used in IMAP select."""
        tools.valves.inbox_folder = "Sent"
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

    @pytest.mark.asyncio
    async def test_archive_email_disabled_by_default(self, tools):
        """Test that archive_email is blocked when allow_archive is False (default)."""
        assert tools.valves.allow_archive is False
        result = await tools.archive_email(email_index=1)
        assert "disabled" in result.lower() and "allow_archive" in result

    @pytest.mark.asyncio
    async def test_archive_email_success(self, tools):
        """Test archiving a specific email."""
        tools.valves.allow_archive = True
        raw1 = _make_raw_email("alice@example.com", "bob@example.com", "Hello", "Hi Bob.")
        raw2 = _make_raw_email("carol@example.com", "bob@example.com", "Invoice", "Please pay.")
        emails = [(raw1, "1"), (raw2, "2")]
        mock_server = _make_mock_server(emails)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.archive_email(email_index=1)
        assert "archived" in result.lower() and "successfully" in result.lower()
        copy_calls = [c for c in mock_server.uid.call_args_list if c[0][0] == "COPY"]
        assert len(copy_calls) == 1

    @pytest.mark.asyncio
    async def test_archive_email_out_of_range(self, tools):
        """Test archiving an email with an out-of-range index."""
        tools.valves.allow_archive = True
        raw = _make_raw_email("test@example.com", "u@example.com", "Test", "Body")
        mock_server = _make_mock_server([(raw, "1")])
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.archive_email(email_index=99)
        assert "out of range" in result.lower()

    @pytest.mark.asyncio
    async def test_archive_email_empty_mailbox(self, tools):
        """Test archiving from an empty mailbox."""
        tools.valves.allow_archive = True
        mock_server = _make_mock_server([])
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.archive_email(email_index=1)
        assert "empty" in result.lower() or "Nothing to archive" in result

    @pytest.mark.asyncio
    async def test_archive_email_no_credentials(self):
        """Test that archive_email returns error when credentials are missing."""
        t = Tools()
        t.valves.allow_archive = True
        result = await t.archive_email(email_index=1)
        assert "Error" in result and "credentials" in result

    @pytest.mark.asyncio
    async def test_archive_default_folder(self, tools):
        """Test that the default archive folder is 'Archive'."""
        assert tools.valves.archive_folder == "Archive"

    @pytest.mark.asyncio
    async def test_archive_custom_folder(self, tools):
        """Test archiving to a custom folder."""
        tools.valves.allow_archive = True
        tools.valves.archive_folder = "Gmail/All Mail"
        raw = _make_raw_email("sender@test.com", "receiver@test.com", "Test", "Body")
        emails = [(raw, "1")]

        def override_uid(cmd, criteria=None, *args, **kwargs):
            if cmd == "search":
                return ("OK", [b"1"])
            elif cmd == "COPY":
                assert args[0] == "Gmail/All Mail"
                return ("OK", [b"COPY completed"])
            elif cmd == "store":
                return ("OK", [b"FLAGS (\\Deleted)"])
            return ("OK", [b""])

        mock_server = _make_mock_server(emails, override_uid=override_uid)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.archive_email(email_index=1)
        assert "archived" in result.lower() and "successfully" in result.lower()


class TestAccessGuard:
    """Test the _access_guard helper for folder access control."""

    @pytest.mark.asyncio
    async def test_access_guard_archive_disabled(self, tools):
        """Test _access_guard returns error when archive access is disabled."""
        tools.valves.allow_list_archive = False
        assert tools._access_guard("archive", tools.valves.archive_folder) is not None

    @pytest.mark.asyncio
    async def test_access_guard_inbox_disabled(self, tools):
        """Test _access_guard returns error when inbox access is disabled."""
        tools.valves.allow_list_inbox = False
        assert tools._access_guard("inbox", tools.valves.inbox_folder) is not None

    @pytest.mark.asyncio
    async def test_access_guard_inbox_enabled(self, tools):
        """Test _access_guard allows access when inbox toggle is on."""
        tools.valves.allow_list_inbox = True
        result = tools._access_guard("inbox", tools.valves.inbox_folder)
        assert result is None

    @pytest.mark.asyncio
    async def test_access_guard_archive_enabled(self, tools):
        """Test _access_guard allows access when archive toggle is on."""
        tools.valves.allow_list_archive = True
        result = tools._access_guard("archive", tools.valves.archive_folder)
        assert result is None

    @pytest.mark.asyncio
    async def test_access_guard_trash_disabled(self, tools):
        """Test _access_guard returns error when trash access is disabled."""
        tools.valves.allow_list_trash = False
        assert tools._access_guard("trash", tools.valves.trash_folder) is not None

    @pytest.mark.asyncio
    async def test_access_guard_trash_enabled(self, tools):
        """Test _access_guard allows access when trash toggle is on."""
        tools.valves.allow_list_trash = True
        result = tools._access_guard("trash", tools.valves.trash_folder)
        assert result is None

    @pytest.mark.asyncio
    async def test_access_guard_sent_disabled(self, tools):
        """Test _access_guard returns error when sent access is disabled."""
        tools.valves.allow_list_sent = False
        assert tools._access_guard("sent", tools.valves.sent_folder) is not None

    @pytest.mark.asyncio
    async def test_access_guard_sent_enabled(self, tools):
        """Test _access_guard allows access when sent toggle is on."""
        tools.valves.allow_list_sent = True
        result = tools._access_guard("sent", tools.valves.sent_folder)
        assert result is None

    @pytest.mark.asyncio
    async def test_access_guard_drafts_disabled(self, tools):
        """Test _access_guard returns error when drafts access is disabled."""
        tools.valves.allow_list_drafts = False
        assert tools._access_guard("drafts", tools.valves.drafts_folder) is not None

    @pytest.mark.asyncio
    async def test_access_guard_drafts_enabled(self, tools):
        """Test _access_guard allows access when drafts toggle is on."""
        tools.valves.allow_list_drafts = True
        result = tools._access_guard("drafts", tools.valves.drafts_folder)
        assert result is None

    @pytest.mark.asyncio
    async def test_access_guard_wrong_folder_returns_error(self, tools):
        """Test _access_guard returns error when folder differs from configured default."""
        tools.valves.allow_list_trash = True
        tools.valves.trash_folder = "Trash"
        result = tools._access_guard("trash", "Different/Trash")
        assert result is not None
        assert "disabled" in result.lower()


class TestResolveFolder:
    """Test the _resolve_folder helper."""

    @pytest.mark.asyncio
    async def test_resolve_folder_explicit(self, tools):
        """Test _resolve_folder returns explicit folder when provided."""
        assert tools._resolve_folder(folder="Some/Folder", fallback="INBOX") == "Some/Folder"

    @pytest.mark.asyncio
    async def test_resolve_folder_fallback(self, tools):
        """Test _resolve_folder falls back to valve folder."""
        tools.valves.inbox_folder = "INBOX"
        assert tools._resolve_folder(folder=None, fallback="INBOX") == "INBOX"

    @pytest.mark.asyncio
    async def test_resolve_folder_none_fallback(self, tools):
        """Test _resolve_folder returns default when nothing is set."""
        assert tools._resolve_folder(folder=None, fallback=None) == "INBOX"


class TestArchiveMethods:
    """Test the list_archive_emails and read_archive_email convenience methods."""

    @pytest.mark.asyncio
    async def test_list_archive_disabled_by_default(self, tools):
        """Test list_archive_emails is blocked when allow_list_archive is False."""
        assert tools.valves.allow_list_archive is False
        result = await tools.list_archive_emails(count=5)
        assert "disabled" in result.lower() and "allow_list_archive" in result

    @pytest.mark.asyncio
    async def test_list_archive_enabled_with_messages(self, tools):
        """Test listing archived emails when access is enabled."""
        tools.valves.allow_list_archive = True
        raw1 = _make_raw_email("alice@example.com", "bob@example.com", "Archived A", "Body A")
        raw2 = _make_raw_email("carol@example.com", "bob@example.com", "Archived B", "Body B")
        emails = [(raw1, "1"), (raw2, "2")]
        mock_server = _make_mock_server(emails)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.list_archive_emails(count=10)
        assert "Archived A" in result
        assert "Archived B" in result
        assert "Archive" in result

    @pytest.mark.asyncio
    async def test_list_archive_enabled_custom_folder(self, tools):
        """Test listing archived emails from a custom folder path."""
        tools.valves.allow_list_archive = True
        tools.valves.archive_folder = "Gmail/All Mail"
        raw = _make_raw_email("sender@test.com", "receiver@test.com", "Test", "Body")
        emails = [(raw, "1")]

        def override_uid(cmd, criteria=None, *args, **kwargs):
            if cmd == "search":
                return ("OK", [b"1"])
            elif cmd == "fetch":
                return ("OK", [_make_mock_email_data(raw, "1")])
            return ("OK", [b""])

        mock_server = _make_mock_server(emails, override_uid=override_uid)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.list_archive_emails(count=10)
        assert "Test" in result
        assert "Gmail/All Mail" in result

    @pytest.mark.asyncio
    async def test_list_archive_empty(self, tools):
        """Test listing archived emails from an empty archive folder."""
        tools.valves.allow_list_archive = True
        mock_server = _make_mock_server([])
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.list_archive_emails(count=10)
        assert "empty" in result.lower() or "No emails" in result

    @pytest.mark.asyncio
    async def test_read_archive_disabled_by_default(self, tools):
        """Test read_archive_email is blocked when allow_list_archive is False."""
        assert tools.valves.allow_list_archive is False
        result = await tools.read_archive_email(email_index=1)
        assert "disabled" in result.lower() and "allow_list_archive" in result

    @pytest.mark.asyncio
    async def test_read_archive_enabled(self, tools):
        """Test reading an archived email when access is enabled."""
        tools.valves.allow_list_archive = True
        raw = _make_raw_email("alice@example.com", "bob@example.com", "Archived Message", "This is body content.")
        emails = [(raw, "1")]
        mock_server = _make_mock_server(emails)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.read_archive_email(email_index=1)
        assert "Archived Message" in result
        assert "Archive" in result
        assert "This is body content" in result

    @pytest.mark.asyncio
    async def test_read_archive_out_of_range(self, tools):
        """Test reading an archived email with an out-of-range index."""
        tools.valves.allow_list_archive = True
        raw = _make_raw_email("test@example.com", "u@example.com", "Test", "Body")
        mock_server = _make_mock_server([(raw, "1")])
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.read_archive_email(email_index=99)
        assert "out of range" in result.lower()

    @pytest.mark.asyncio
    async def test_read_archive_empty_folder(self, tools):
        """Test reading from an empty archive folder."""
        tools.valves.allow_list_archive = True
        mock_server = _make_mock_server([])
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.read_archive_email(email_index=1)
        assert "empty" in result.lower() or "No emails" in result

    @pytest.mark.asyncio
    async def test_list_archive_no_credentials(self):
        """Test list_archive_emails returns error when credentials are missing."""
        t = Tools()
        t.valves.allow_list_archive = True
        result = await t.list_archive_emails()
        assert "Error" in result and "credentials" in result

    @pytest.mark.asyncio
    async def test_archive_custom_folder_default(self, tools):
        """Test default archive folder is 'Archive'."""
        assert tools.valves.archive_folder == "Archive"


class TestTrashMethods:
    """Test the list_trash_emails and read_trash_email convenience methods."""

    @pytest.mark.asyncio
    async def test_list_trash_disabled_by_default(self, tools):
        """Test list_trash_emails is blocked when allow_list_trash is False."""
        assert tools.valves.allow_list_trash is False
        result = await tools.list_trash_emails(count=5)
        assert "disabled" in result.lower() and "allow_list_trash" in result

    @pytest.mark.asyncio
    async def test_list_trash_enabled(self, tools):
        """Test listing trash emails when access is enabled."""
        tools.valves.allow_list_trash = True
        raw = _make_raw_email("sender@test.com", "recv@test.com", "Trashed", "Trash body")
        emails = [(raw, "1")]
        mock_server = _make_mock_server(emails)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.list_trash_emails(count=10)
        assert "Trashed" in result
        assert "Trash" in result

    @pytest.mark.asyncio
    async def test_list_trash_custom_folder(self, tools):
        """Test listing trash emails from a custom folder like 'Deleted Items'."""
        tools.valves.allow_list_trash = True
        tools.valves.trash_folder = "Deleted Items"
        raw = _make_raw_email("sender@test.com", "recv@test.com", "Deleted", "Body")
        emails = [(raw, "1")]

        def override_uid(cmd, criteria=None, *args, **kwargs):
            if cmd == "search":
                return ("OK", [b"1"])
            elif cmd == "fetch":
                return ("OK", [_make_mock_email_data(raw, "1")])
            return ("OK", [b""])

        mock_server = _make_mock_server(emails, override_uid=override_uid)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.list_trash_emails(count=10)
        assert "Deleted" in result
        assert "Deleted Items" in result

    @pytest.mark.asyncio
    async def test_read_trash_enabled(self, tools):
        """Test reading a trash email when access is enabled."""
        tools.valves.allow_list_trash = True
        raw = _make_raw_email("sender@test.com", "recv@test.com", "Trash Msg", "Trash body")
        emails = [(raw, "1")]
        mock_server = _make_mock_server(emails)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.read_trash_email(email_index=1)
        assert "Trash Msg" in result
        assert "Trash" in result


class TestSentMethods:
    """Test the list_sent_emails and read_sent_email convenience methods."""

    @pytest.mark.asyncio
    async def test_list_sent_disabled_by_default(self, tools):
        """Test list_sent_emails is blocked when allow_list_sent is False."""
        assert tools.valves.allow_list_sent is False
        result = await tools.list_sent_emails(count=5)
        assert "disabled" in result.lower() and "allow_list_sent" in result

    @pytest.mark.asyncio
    async def test_list_sent_enabled(self, tools):
        """Test listing sent emails when access is enabled."""
        tools.valves.allow_list_sent = True
        raw = _make_raw_email("me@test.com", "you@test.com", "Sent Msg", "Sent body")
        emails = [(raw, "1")]
        mock_server = _make_mock_server(emails)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.list_sent_emails(count=10)
        assert "Sent Msg" in result
        assert "Sent" in result

    @pytest.mark.asyncio
    async def test_read_sent_enabled(self, tools):
        """Test reading a sent email when access is enabled."""
        tools.valves.allow_list_sent = True
        raw = _make_raw_email("me@test.com", "you@test.com", "Outgoing", "Outgoing body")
        emails = [(raw, "1")]
        mock_server = _make_mock_server(emails)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.read_sent_email(email_index=1)
        assert "Outgoing" in result
        assert "Sent" in result


class TestDraftsMethods:
    """Test the list_draft_emails convenience method."""

    @pytest.mark.asyncio
    async def test_list_drafts_disabled_by_default(self, tools):
        """Test list_draft_emails is blocked when allow_list_drafts is False."""
        assert tools.valves.allow_list_drafts is False
        result = await tools.list_draft_emails(count=5)
        assert "disabled" in result.lower() and "allow_list_drafts" in result

    @pytest.mark.asyncio
    async def test_list_drafts_enabled(self, tools):
        """Test listing draft emails when access is enabled."""
        tools.valves.allow_list_drafts = True
        raw = _make_raw_email("me@test.com", "you@test.com", "Draft Msg", "Draft body")
        emails = [(raw, "1")]
        mock_server = _make_mock_server(emails)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.list_draft_emails(count=10)
        assert "Draft Msg" in result
        assert "Drafts" in result

    @pytest.mark.asyncio
    async def test_list_drafts_no_read_method(self, tools):
        """Verify read_draft_email convenience does not exist (drafts are typically read-only)."""
        assert not hasattr(tools, "read_draft_email")


class TestFolderParamOverride:
    """Test passing explicit folder parameter to existing methods."""

    @pytest.mark.asyncio
    async def test_list_emails_folder_param(self, tools):
        """Test list_emails respects explicit folder param."""
        raw = _make_raw_email("test@example.com", "u@example.com", "Hello", "Body")
        emails = [(raw, "1")]
        mock_server = _make_mock_server(emails)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.list_emails(folder="Custom/Folder", count=10)
        assert "Hello" in result
        assert "Custom/Folder" in result
        assert "Hello" in result

    @pytest.mark.asyncio
    async def test_read_email_folder_param(self, tools):
        """Test read_email respects explicit folder param."""
        raw = _make_raw_email("test@example.com", "u@example.com", "Test", "Body")
        emails = [(raw, "1")]
        mock_server = _make_mock_server(emails)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.read_email(email_index=1, folder="Custom/Folder")
        assert "Custom/Folder" in result
        assert "Test" in result

    @pytest.mark.asyncio
    async def test_search_emails_folder_param(self, tools):
        """Test search_emails respects explicit folder param."""
        raw = _make_raw_email("test@example.com", "u@example.com", "Search Me", "Body")
        emails = [(raw, "1")]
        mock_server = _make_mock_server(emails)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.search_emails(query="Search Me", count=10, folder="Custom/Folder")
        assert "Search Me" in result
        assert "Custom/Folder" in result


class TestListInboxEmails:
    """Test the list_inbox_emails convenience method."""

    @pytest.mark.asyncio
    async def test_list_inbox_emails_disabled_by_default(self, tools):
        """Test list_inbox_emails is blocked when allow_list_inbox is False."""
        assert tools.valves.allow_list_inbox is False
        result = await tools.list_inbox_emails(count=5)
        assert "disabled" in result.lower() and "allow_list_inbox" in result

    @pytest.mark.asyncio
    async def test_list_inbox_emails_enabled_with_messages(self, tools):
        """Test listing inbox emails when access is enabled."""
        tools.valves.allow_list_inbox = True
        raw1 = _make_raw_email("alice@example.com", "bob@example.com", "Hello", "Hi Bob, how are you?")
        raw2 = _make_raw_email(
            "carol@example.com", "bob@example.com", "Invoice #123", "Please find attached the invoice."
        )
        emails = [(raw1, "1"), (raw2, "2")]
        mock_server = _make_mock_server(emails)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.list_inbox_emails(count=10)
        assert "alice@example.com" in result
        assert "carol@example.com" in result
        assert "Hello" in result
        assert "Invoice #123" in result

    @pytest.mark.asyncio
    async def test_list_inbox_emails_empty(self, tools):
        """Test listing inbox emails from an empty inbox."""
        tools.valves.allow_list_inbox = True
        mock_server = _make_mock_server([])
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.list_inbox_emails(count=10)
        assert "empty" in result.lower() or "No emails" in result

    @pytest.mark.asyncio
    async def test_list_inbox_emails_no_credentials(self):
        """Test list_inbox_emails returns error when credentials are missing."""
        t = Tools()
        t.valves.allow_list_inbox = True
        result = await t.list_inbox_emails(count=5)
        assert "Error" in result and "credentials" in result


class TestReadInboxEmail:
    """Test the read_inbox_email convenience method."""

    @pytest.mark.asyncio
    async def test_read_inbox_email_disabled_by_default(self, tools):
        """Test read_inbox_email is blocked when allow_list_inbox is False."""
        assert tools.valves.allow_list_inbox is False
        result = await tools.read_inbox_email(email_index=1)
        assert "disabled" in result.lower() and "allow_list_inbox" in result

    @pytest.mark.asyncio
    async def test_read_inbox_email_enabled(self, tools):
        """Test reading an inbox email when access is enabled."""
        tools.valves.allow_list_inbox = True
        raw = _make_raw_email("alice@example.com", "bob@example.com", "Inbox Message", "This is inbox body content.")
        emails = [(raw, "1")]
        mock_server = _make_mock_server(emails)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.read_inbox_email(email_index=1)
        assert "Inbox Message" in result
        assert "INBOX" in result
        assert "This is inbox body content" in result

    @pytest.mark.asyncio
    async def test_read_inbox_email_out_of_range(self, tools):
        """Test reading an inbox email with an out-of-range index."""
        tools.valves.allow_list_inbox = True
        raw = _make_raw_email("test@example.com", "u@example.com", "Test", "Body")
        mock_server = _make_mock_server([(raw, "1")])
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.read_inbox_email(email_index=99)
        assert "out of range" in result.lower()

    @pytest.mark.asyncio
    async def test_read_inbox_email_empty_folder(self, tools):
        """Test reading from an empty inbox folder."""
        tools.valves.allow_list_inbox = True
        mock_server = _make_mock_server([])
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.read_inbox_email(email_index=1)
        assert "empty" in result.lower() or "No emails" in result

    @pytest.mark.asyncio
    async def test_read_inbox_email_no_credentials(self):
        """Test read_inbox_email returns error when credentials are missing."""
        t = Tools()
        t.valves.allow_list_inbox = True
        result = await t.read_inbox_email(email_index=1)
        assert "Error" in result and "credentials" in result


class TestListEmailsExplicitFolder:
    """Test the list_emails method with required folder parameter."""

    @pytest.mark.asyncio
    async def test_list_emails_requires_folder(self):
        """Test that list_emails raises TypeError when folder is not provided."""
        t = Tools()
        t.valves.imap_server = "mail.example.com"
        t.valves.imap_port = 993
        t.valves.username = "testuser"
        t.valves.password = "testpass"
        with pytest.raises(TypeError):
            await t.list_emails(count=5)  # pyright: ignore

    @pytest.mark.asyncio
    async def test_list_emails_with_custom_folder(self, tools):
        """Test list_emails with a custom folder."""
        raw = _make_raw_email("sender@test.com", "recv@test.com", "Custom Folder", "Body content")
        emails = [(raw, "1")]
        mock_server = _make_mock_server(emails)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.list_emails(folder="Custom/Folder", count=10)
        assert "Custom/Folder" in result
        assert "Custom Folder" in result

    @pytest.mark.asyncio
    async def test_list_emails_empty_custom_folder(self, tools):
        """Test list_emails with empty custom folder."""
        mock_server = _make_mock_server([])
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.list_emails(folder="Empty/Folder", count=10)
        assert "empty" in result.lower() or "No emails" in result


class TestDefaultValueToggles:
    """Test that all new toggles default to False and folder names are reasonable."""

    @pytest.mark.asyncio
    async def test_all_toggles_disabled_by_default(self):
        """Test that all folder read-access toggles default to False."""
        t = Tools()
        assert t.valves.allow_list_inbox is False
        assert t.valves.allow_list_archive is False
        assert t.valves.allow_list_trash is False
        assert t.valves.allow_list_sent is False
        assert t.valves.allow_list_drafts is False

    @pytest.mark.asyncio
    async def test_default_folder_names(self):
        """Test that default folder names are reasonable."""
        t = Tools()
        assert t.valves.inbox_folder == "INBOX"
        assert t.valves.archive_folder == "Archive"
        assert t.valves.trash_folder == "Trash"
        assert t.valves.sent_folder == "Sent"
        assert t.valves.drafts_folder == "Drafts"


class TestMimeHeaderDecodingEncoded:
    """Test MIME header decoding with RFC 2047 encoded values."""

    @pytest.mark.asyncio
    async def test_decode_mime_header_encoded_utf8(self, tools):
        """Test decoding RFC 2047 encoded UTF-8 header."""
        encoded = "=?utf-8?b?VGVzdCBzdWJqZWN0?="
        result = tools._decode_mime_header(encoded)
        assert result == "Test subject"

    @pytest.mark.asyncio
    async def test_decode_mime_header_encoded_q(self, tools):
        """Test decoding RFC 2047 encoded-Q header."""
        encoded = "=?utf-8?q?Test_Subject?="
        result = tools._decode_mime_header(encoded)
        assert result == "Test Subject"

    @pytest.mark.asyncio
    async def test_decode_mime_header_multiple_encoded_parts(self, tools):
        """Test decoding header with multiple encoded parts."""
        encoded = "=?utf-8?b?VGVzdA==?= =?utf-8?b?IFN1YmplY3Q?="
        result = tools._decode_mime_header(encoded)
        assert "Test" in result

    @pytest.mark.asyncio
    async def test_decode_mime_header_unknown_charset(self, tools):
        """Test decoding with unknown charset falls back to utf-8."""
        encoded = rb"=\?unknown-charset?b?dGVzdA=="
        result = tools._decode_mime_header(encoded.decode())
        assert result != ""


class TestGetEmailBody:
    """Test _get_email_body extraction logic."""

    @pytest.mark.asyncio
    async def test_get_email_body_multipart_plain_only(self, tools):
        """Test extracting body from a multipart email with plain text part."""
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        msg = MIMEMultipart("mixed")
        msg["From"] = "a@b.com"
        msg["To"] = "c@d.com"
        msg["Subject"] = "Multibody"
        text_part = MIMEText("Plain body content", "plain")
        html_part = MIMEText("<p>HTML body</p>", "html")
        msg.attach(text_part)
        msg.attach(html_part)
        body = tools._get_email_body(msg)
        assert body == "Plain body content"

    @pytest.mark.asyncio
    async def test_get_email_body_multipart_html_only(self, tools):
        """Test extracting body — if no plain part, should return empty string."""
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        msg = MIMEMultipart("mixed")
        msg["From"] = "a@b.com"
        msg["To"] = "c@d.com"
        msg["Subject"] = "HtOnly"
        html_part = MIMEText("<p>HTML only</p>", "html")
        msg.attach(html_part)
        body = tools._get_email_body(msg)
        assert body == ""

    @pytest.mark.asyncio
    async def test_get_email_body_multipart_with_attachment(self, tools):
        """Test that attachment parts in multipart are skipped."""
        from email.mime.base import MIMEBase
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        msg = MIMEMultipart("mixed")
        msg["From"] = "a@b.com"
        msg["To"] = "c@d.com"
        msg["Subject"] = "Attach test"
        plain_part = MIMEText("Real content here", "plain")
        msg.attach(plain_part)
        attachment = MIMEBase("application", "pdf")
        attachment.set_payload(b"fake pdf data")
        attachment.add_header("Content-Disposition", "attachment", filename="doc.pdf")
        msg.attach(attachment)
        body = tools._get_email_body(msg)
        assert body == "Real content here"

    @pytest.mark.asyncio
    async def test_get_email_body_truncation(self, tools):
        """Test that body is truncated at max_chars."""
        from email.mime.text import MIMEText

        msg = MIMEText("A" * 500, "plain")
        msg["From"] = "a@b.com"
        msg["To"] = "c@d.com"
        msg["Subject"] = "Long"
        body = tools._get_email_body(msg, max_chars=50)
        assert len(body) <= 50 + len("\n\n... [truncated]")

    @pytest.mark.asyncio
    async def test_get_email_body_single_non_multipart(self, tools):
        """Test extracting body from a non-multipart email."""
        from email.mime.text import MIMEText

        msg = MIMEText("Hello world plain text", "plain")
        msg["From"] = "a@b.com"
        msg["To"] = "c@d.com"
        msg["Subject"] = "Simple"
        body = tools._get_email_body(msg)
        assert body == "Hello world plain text"

    @pytest.mark.asyncio
    async def test_get_email_body_binary_payload_decode(self, tools):
        """Test body extraction when payload is bytes with a charset."""
        from email.mime.text import MIMEText

        msg = MIMEText("Accents: caf\u00e9 r\u00e9sum\u00e9", "plain")
        msg["From"] = "a@b.com"
        msg["To"] = "c@d.com"
        msg["Subject"] = "Accents"
        body = tools._get_email_body(msg)
        assert "caf\u00e9" in body


class TestNonSSLConnection:
    """Test non-SSL connection path."""

    @pytest.mark.asyncio
    async def test_list_inbox_emails_non_ssl(self, tools):
        """Test that encryption_method='starttls' connects via imaplib.IMAP4 with STARTTLS."""
        tools.valves.encryption_method = EncryptionMode.starttls
        tools.valves.imap_port = 143
        tools.valves.allow_list_inbox = True
        raw = _make_raw_email("sender@test.com", "recv@test.com", "Hello", "Body")
        emails = [(raw, "1")]
        mock_server = _make_mock_server(emails)
        with (
            patch("imaplib.IMAP4", return_value=mock_server) as mock_imap4,
            patch("imaplib.IMAP4_SSL"),
        ):
            result = await tools.list_inbox_emails(count=10)
        mock_imap4.assert_called_once()
        assert "Hello" in result

    @pytest.mark.asyncio
    async def test_list_inbox_emails_ssl_true_uses_ssl(self, tools):
        """Test that encryption_method='implicit' (default) connects via imaplib.IMAP4_SSL."""
        tools.valves.encryption_method = EncryptionMode.implicit
        tools.valves.allow_list_inbox = True
        raw = _make_raw_email("sender@test.com", "recv@test.com", "Hello", "Body")
        emails = [(raw, "1")]
        mock_server = _make_mock_server(emails)
        with (
            patch("imaplib.IMAP4_SSL", return_value=mock_server) as mock_imap4_ssl,
            patch("imaplib.IMAP4"),
        ):
            result = await tools.list_inbox_emails(count=10)
        mock_imap4_ssl.assert_called_once()
        assert "Hello" in result


class TestSearchEmailsAdditional:
    """Additional search_emails tests: date queries, combined criteria, no results."""

    @pytest.mark.asyncio
    async def test_search_emails_no_results(self, tools):
        """Test search returning no matching emails."""

        def override_uid(cmd, criteria=None, *args, **kwargs):
            if cmd == "search":
                return ("OK", [b""])
            return ("OK", [b""])

        mock_server = _make_mock_server([], override_uid=override_uid)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.search_emails(query='subject:"nonexistent"')
        assert "No emails found matching criteria" in result

    @pytest.mark.asyncio
    async def test_search_emails_after_date(self, tools):
        """Test search with after: date filter."""
        raw = _make_raw_email("alice@example.com", "bob@example.com", "After test", "Hi")
        emails = [(raw, "1")]
        mock_server = _make_mock_server(emails)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            # We expect the uid search call to contain SINCE
            result = await tools.search_emails(query="after:2025-04-01", count=10)
        # The mock server handles search with ANY criteria via the ALL branch
        assert "alice@example.com" in result

    @pytest.mark.asyncio
    async def test_search_emails_before_date(self, tools):
        """Test search with before: date filter."""
        raw = _make_raw_email("alice@example.com", "bob@example.com", "Before test", "Hi")
        emails = [(raw, "1")]
        mock_server = _make_mock_server(emails)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.search_emails(query="before:2025-12-01", count=10)
        assert "alice@example.com" in result

    @pytest.mark.asyncio
    async def test_search_emails_before_after_combined(self, tools):
        """Test search combining before: and after:."""
        raw = _make_raw_email("alice@example.com", "bob@example.com", "Range test", "Hi")
        emails = [(raw, "1")]
        mock_server = _make_mock_server(emails)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.search_emails(query="after:2025-01-01 before:2025-12-31", count=10)
        assert "alice@example.com" in result

    @pytest.mark.asyncio
    async def test_search_emails_combined_from_and_subject(self, tools):
        """Test search with both from: and subject:."""
        raw = _make_raw_email("alice@example.com", "bob@example.com", "Pay me", "Invoice")
        raw2 = _make_raw_email("carol@example.com", "bob@example.com", "Hello", "Invoice")
        emails = [(raw, "1"), (raw2, "2")]
        mock_server = _make_mock_server(emails)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.search_emails(query='from:"alice@example.com" subject:"Invoice"', count=10)
        assert "alice@example.com" in result
        assert "carol@example.com" not in result

    @pytest.mark.asyncio
    async def test_search_emails_free_text_no_match(self, tools):
        """Test free-text search that matches no email."""
        raw = _make_raw_email("alice@example.com", "bob@example.com", "Hello", "World")
        emails = [(raw, "1")]
        mock_server = _make_mock_server(emails)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.search_emails(query="xyznotfound", count=10)
        assert "No emails found" in result


class TestAttachmentDisplay:
    """Test attachment info display in listing and reading."""

    @pytest.mark.asyncio
    async def test_list_inbox_emails_with_attachments(self, tools):
        """Test that list_inbox_emails shows attachment count."""
        from email.mime.base import MIMEBase
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        msg = MIMEMultipart("mixed")
        msg["From"] = "sender@test.com"
        msg["To"] = "recv@test.com"
        msg["Subject"] = "AttachMsg"
        plain = MIMEText("Body text", "plain")
        msg.attach(plain)

        for i in range(3):
            att = MIMEBase("application", "octet-stream")
            att.set_payload(f"data{i}".encode())
            att.add_header("Content-Disposition", "attachment", filename=f"file{i}.pdf")
            msg.attach(att)

        emails = [(msg.as_bytes(), "1")]
        tools.valves.allow_list_inbox = True
        mock_server = _make_mock_server(emails)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.list_inbox_emails(count=10)

        assert "AttachMsg" in result
        assert "3 attachment(s)" in result

    @pytest.mark.asyncio
    async def test_read_email_with_attachments(self, tools):
        """Test that read_email shows attachment info."""
        from email.mime.base import MIMEBase
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        msg = MIMEMultipart("mixed")
        msg["From"] = "sender@test.com"
        msg["To"] = "recv@test.com"
        msg["Subject"] = "ReadAttach"
        plain = MIMEText("Body text here", "plain")
        msg.attach(plain)

        att = MIMEBase("application", "pdf")
        att.set_payload(b"data")
        att.add_header("Content-Disposition", "attachment", filename="doc.pdf")
        msg.attach(att)

        emails = [(msg.as_bytes(), "1")]
        mock_server = _make_mock_server(emails)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.read_email(email_index=1)

        assert "ReadAttach" in result
        assert "Attachments:" in result
        assert "1 file(s) attached" in result


class TestIMAPErrorsInOtherMethods:
    """Test IMAP exceptions are caught and returned as error strings in all public methods."""

    @pytest.mark.asyncio
    async def test_list_emails_imap_error(self, tools):
        """Test IMAP error handling in list_emails."""
        mock_server = MagicMock()
        mock_server.login.side_effect = _IMAP_EXCEPTION("Connection refused")
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.list_emails(folder="INBOX", count=5)
        assert "IMAP Error" in result

    @pytest.mark.asyncio
    async def test_list_inbox_emails_imap_error(self, tools):
        """Test IMAP error handling in list_inbox_emails."""
        tools.valves.allow_list_inbox = True
        mock_server = MagicMock()
        mock_server.login.side_effect = _IMAP_EXCEPTION("Connection refused")
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.list_inbox_emails(count=5)
        assert "IMAP Error" in result

    @pytest.mark.asyncio
    async def test_read_email_imap_error(self, tools):
        """Test IMAP error handling in read_email."""
        mock_server = MagicMock()
        mock_server.login.side_effect = _IMAP_EXCEPTION("Authentication failed")
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.read_email(email_index=1)
        assert "IMAP Error" in result

    @pytest.mark.asyncio
    async def test_read_inbox_email_imap_error(self, tools):
        """Test IMAP error handling in read_inbox_email."""
        tools.valves.allow_list_inbox = True
        mock_server = MagicMock()
        mock_server.login.side_effect = _IMAP_EXCEPTION("Authentication failed")
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.read_inbox_email(email_index=1)
        assert "IMAP Error" in result

    @pytest.mark.asyncio
    async def test_search_emails_imap_error(self, tools):
        """Test IMAP error handling in search_emails."""
        mock_server = MagicMock()
        mock_server.login.side_effect = _IMAP_EXCEPTION("Timeout")
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.search_emails(query="test", count=10)
        assert "IMAP Error" in result

    @pytest.mark.asyncio
    async def test_delete_email_imap_error(self, tools):
        """Test IMAP error handling in delete_email."""
        tools.valves.allow_delete_single = True
        mock_server = MagicMock()
        mock_server.login.side_effect = _IMAP_EXCEPTION("Disk error")
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.delete_email(email_index=1)
        assert "IMAP Error" in result

    @pytest.mark.asyncio
    async def test_delete_all_emails_imap_error(self, tools):
        """Test IMAP error handling in delete_all_emails."""
        tools.valves.allow_delete_all = True
        mock_server = MagicMock()
        mock_server.login.side_effect = _IMAP_EXCEPTION("Disk error")
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.delete_all_emails()
        assert "IMAP Error" in result

    @pytest.mark.asyncio
    async def test_archive_email_imap_error(self, tools):
        """Test IMAP error handling in archive_email."""
        tools.valves.allow_archive = True
        mock_server = MagicMock()
        mock_server.login.side_effect = _IMAP_EXCEPTION("Disk error")
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.archive_email(email_index=1)
        assert "IMAP Error" in result


class TestGenericExceptionErrors:
    """Test that generic (non-IMAP) exceptions are caught and returned properly."""

    @pytest.mark.asyncio
    async def test_list_emails_generic_error(self, tools):
        """Test generic exception handling in list_emails."""
        with patch("imap_mailbox._IMAP_EXCEPTION", OSError):
            mock_server = MagicMock()
            mock_server.login.side_effect = NotImplementedError("Generic error")
            with patch("imaplib.IMAP4_SSL", return_value=mock_server):
                result = await tools.list_emails(folder="INBOX", count=5)
            assert "Error connecting to IMAP server" in result

    @pytest.mark.asyncio
    async def test_list_inbox_emails_generic_error(self, tools):
        """Test generic exception handling in list_inbox_emails."""
        tools.valves.allow_list_inbox = True
        with patch("imap_mailbox._IMAP_EXCEPTION", OSError):
            mock_server = MagicMock()
            mock_server.login.side_effect = NotImplementedError("Generic error")
            with patch("imaplib.IMAP4_SSL", return_value=mock_server):
                result = await tools.list_inbox_emails(count=5)
            assert "Error connecting to IMAP server" in result

    @pytest.mark.asyncio
    async def test_read_email_generic_error(self, tools):
        """Test generic exception handling in read_email."""
        with patch("imap_mailbox._IMAP_EXCEPTION", OSError):
            mock_server = MagicMock()
            mock_server.login.side_effect = NotImplementedError("Generic error")
            with patch("imaplib.IMAP4_SSL", return_value=mock_server):
                result = await tools.read_email(email_index=1)
            assert "Error reading email" in result

    @pytest.mark.asyncio
    async def test_read_inbox_email_generic_error(self, tools):
        """Test generic exception handling in read_inbox_email."""
        tools.valves.allow_list_inbox = True
        with patch("imap_mailbox._IMAP_EXCEPTION", OSError):
            mock_server = MagicMock()
            mock_server.login.side_effect = NotImplementedError("Generic error")
            with patch("imaplib.IMAP4_SSL", return_value=mock_server):
                result = await tools.read_inbox_email(email_index=1)
            assert "Error reading email" in result

    @pytest.mark.asyncio
    async def test_search_emails_generic_error(self, tools):
        """Test generic exception handling in search_emails."""
        with patch("imap_mailbox._IMAP_EXCEPTION", OSError):
            mock_server = MagicMock()
            mock_server.login.side_effect = NotImplementedError("Generic error")
            with patch("imaplib.IMAP4_SSL", return_value=mock_server):
                result = await tools.search_emails(query="test", count=10)
            assert "Error searching emails" in result

    @pytest.mark.asyncio
    async def test_delete_email_generic_error(self, tools):
        """Test generic exception handling in delete_email."""
        tools.valves.allow_delete_single = True
        with patch("imap_mailbox._IMAP_EXCEPTION", OSError):
            mock_server = MagicMock()
            mock_server.login.side_effect = NotImplementedError("Generic error")
            with patch("imaplib.IMAP4_SSL", return_value=mock_server):
                result = await tools.delete_email(email_index=1)
            assert "Error deleting email" in result

    @pytest.mark.asyncio
    async def test_delete_all_emails_generic_error(self, tools):
        """Test generic exception handling in delete_all_emails."""
        tools.valves.allow_delete_all = True
        with patch("imap_mailbox._IMAP_EXCEPTION", OSError):
            mock_server = MagicMock()
            mock_server.login.side_effect = NotImplementedError("Generic error")
            with patch("imaplib.IMAP4_SSL", return_value=mock_server):
                result = await tools.delete_all_emails()
            assert "Error deleting emails" in result

    @pytest.mark.asyncio
    async def test_archive_email_generic_error(self, tools):
        """Test generic exception handling in archive_email."""
        tools.valves.allow_archive = True
        with patch("imap_mailbox._IMAP_EXCEPTION", OSError):
            mock_server = MagicMock()
            mock_server.login.side_effect = NotImplementedError("Generic error")
            with patch("imaplib.IMAP4_SSL", return_value=mock_server):
                result = await tools.archive_email(email_index=1)
            assert "Error archiving email" in result

    @pytest.mark.asyncio
    async def test_list_archive_emails_generic_error(self, tools):
        """Test generic exception handling in list_archive_emails."""
        tools.valves.allow_list_archive = True
        with patch("imap_mailbox._IMAP_EXCEPTION", OSError):
            mock_server = MagicMock()
            mock_server.login.side_effect = NotImplementedError("Generic error")
            with patch("imaplib.IMAP4_SSL", return_value=mock_server):
                result = await tools.list_archive_emails(count=10)
            assert "Error connecting to IMAP server" in result

    @pytest.mark.asyncio
    async def test_read_archive_email_generic_error(self, tools):
        """Test generic exception handling in read_archive_email."""
        tools.valves.allow_list_archive = True
        with patch("imap_mailbox._IMAP_EXCEPTION", OSError):
            mock_server = MagicMock()
            mock_server.login.side_effect = NotImplementedError("Generic error")
            with patch("imaplib.IMAP4_SSL", return_value=mock_server):
                result = await tools.read_archive_email(email_index=1)
            assert "Error reading email" in result

    @pytest.mark.asyncio
    async def test_list_trash_emails_generic_error(self, tools):
        """Test generic exception handling in list_trash_emails."""
        tools.valves.allow_list_trash = True
        with patch("imap_mailbox._IMAP_EXCEPTION", OSError):
            mock_server = MagicMock()
            mock_server.login.side_effect = NotImplementedError("Generic error")
            with patch("imaplib.IMAP4_SSL", return_value=mock_server):
                result = await tools.list_trash_emails(count=10)
            assert "Error connecting to IMAP server" in result

    @pytest.mark.asyncio
    async def test_read_trash_email_generic_error(self, tools):
        """Test generic exception handling in read_trash_email."""
        tools.valves.allow_list_trash = True
        with patch("imap_mailbox._IMAP_EXCEPTION", OSError):
            mock_server = MagicMock()
            mock_server.login.side_effect = NotImplementedError("Generic error")
            with patch("imaplib.IMAP4_SSL", return_value=mock_server):
                result = await tools.read_trash_email(email_index=1)
            assert "Error reading email" in result

    @pytest.mark.asyncio
    async def test_list_sent_emails_generic_error(self, tools):
        """Test generic exception handling in list_sent_emails."""
        tools.valves.allow_list_sent = True
        with patch("imap_mailbox._IMAP_EXCEPTION", OSError):
            mock_server = MagicMock()
            mock_server.login.side_effect = NotImplementedError("Generic error")
            with patch("imaplib.IMAP4_SSL", return_value=mock_server):
                result = await tools.list_sent_emails(count=10)
            assert "Error connecting to IMAP server" in result

    @pytest.mark.asyncio
    async def test_read_sent_email_generic_error(self, tools):
        """Test generic exception handling in read_sent_email."""
        tools.valves.allow_list_sent = True
        with patch("imap_mailbox._IMAP_EXCEPTION", OSError):
            mock_server = MagicMock()
            mock_server.login.side_effect = NotImplementedError("Generic error")
            with patch("imaplib.IMAP4_SSL", return_value=mock_server):
                result = await tools.read_sent_email(email_index=1)
            assert "Error reading email" in result

    @pytest.mark.asyncio
    async def test_list_draft_emails_generic_error(self, tools):
        """Test generic exception handling in list_draft_emails."""
        tools.valves.allow_list_drafts = True
        with patch("imap_mailbox._IMAP_EXCEPTION", OSError):
            mock_server = MagicMock()
            mock_server.login.side_effect = NotImplementedError("Generic error")
            with patch("imaplib.IMAP4_SSL", return_value=mock_server):
                result = await tools.list_draft_emails(count=10)
            assert "Error connecting to IMAP server" in result

    @pytest.mark.asyncio
    async def test_list_emails_server_not_configured(self, tools):
        """Test that list_emails returns error when imap_server is empty."""
        tools = Tools()
        tools.valves.username = "testuser"
        tools.valves.password = "testpass"
        result = await tools.list_emails(folder="INBOX", count=5)
        assert "Error" in result and "server" in result

    @pytest.mark.asyncio
    async def test_list_inbox_emails_server_not_configured(self, tools):
        """Test that list_inbox_emails returns error when imap_server is empty."""
        t = Tools()
        t.valves.username = "testuser"
        t.valves.password = "testpass"
        t.valves.allow_list_inbox = True
        result = await t.list_inbox_emails(count=5)
        assert "Error" in result and "server" in result

    @pytest.mark.asyncio
    async def test_read_email_server_not_configured(self, tools):
        """Test that read_email returns error when imap_server is empty."""
        tools = Tools()
        tools.valves.username = "testuser"
        tools.valves.password = "testpass"
        result = await tools.read_email(email_index=1)
        assert "Error" in result and "server" in result

    @pytest.mark.asyncio
    async def test_search_emails_server_not_configured(self, tools):
        """Test that search_emails returns error when imap_server is empty."""
        tools = Tools()
        tools.valves.username = "testuser"
        tools.valves.password = "testpass"
        result = await tools.search_emails(query="test", count=10)
        assert "Error" in result and "server" in result

    @pytest.mark.asyncio
    async def test_delete_email_server_not_configured(self, tools):
        """Test that delete_email returns error when imap_server is empty."""
        tools = Tools()
        tools.valves.username = "testuser"
        tools.valves.password = "testpass"
        tools.valves.allow_delete_single = True
        result = await tools.delete_email(email_index=1)
        assert "Error" in result and "server" in result

    @pytest.mark.asyncio
    async def test_delete_all_emails_server_not_configured(self, tools):
        """Test that delete_all_emails returns error when imap_server is empty."""
        tools = Tools()
        tools.valves.username = "testuser"
        tools.valves.password = "testpass"
        tools.valves.allow_delete_all = True
        result = await tools.delete_all_emails()
        assert "Error" in result and "server" in result

    @pytest.mark.asyncio
    async def test_archive_email_server_not_configured(self, tools):
        """Test that archive_email returns error when imap_server is empty."""
        tools = Tools()
        tools.valves.username = "testuser"
        tools.valves.password = "testpass"
        tools.valves.allow_archive = True
        result = await tools.archive_email(email_index=1)
        assert "Error" in result and "server" in result


class TestArchiveEmailFunctional:
    """Test the archive_email method (the action, not read/list)."""

    @pytest.mark.asyncio
    async def test_archive_email_enabled_success(self, tools):
        """Test archiving an email when permission is enabled."""
        tools.valves.allow_archive = True
        raw = _make_raw_email("alice@example.com", "bob@example.com", "Invoice", "Please pay.")
        mock_server = _make_mock_server([(raw, "3")])
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.archive_email(email_index=1)
        assert "archived" in result.lower()
        assert mock_server.uid.call_args_list[-2][0][0] == "COPY"
        assert mock_server.expunge.called

    @pytest.mark.asyncio
    async def test_archive_email_disabled_by_default(self, tools):
        """Test archive_email is blocked when allow_archive is False."""
        assert tools.valves.allow_archive is False
        result = await tools.archive_email(email_index=1)
        assert "disabled" in result.lower() and "allow_archive" in result

    @pytest.mark.asyncio
    async def test_archive_email_out_of_range(self, tools):
        """Test archiving an email with an out-of-range index."""
        tools.valves.allow_archive = True
        raw = _make_raw_email("a@b.com", "c@d.com", "Test", "Body")
        mock_server = _make_mock_server([(raw, "1")])
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.archive_email(email_index=99)
        assert "out of range" in result.lower()

    @pytest.mark.asyncio
    async def test_archive_email_empty_mailbox(self, tools):
        """Test archiving from an empty mailbox."""
        tools.valves.allow_archive = True
        mock_server = _make_mock_server([])
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.archive_email(email_index=1)
        assert "empty" in result.lower() or "Nothing to archive" in result

    @pytest.mark.asyncio
    async def test_archive_email_custom_folder(self, tools):
        """Test archiving with a custom archive folder."""
        tools.valves.allow_archive = True
        tools.valves.archive_folder = "Gmail/All Mail"
        raw = _make_raw_email("a@b.com", "c@d.com", "Test", "Body")
        mock_server = _make_mock_server([(raw, "1")])
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.archive_email(email_index=1)
        assert "Gmail/All Mail" in result
        copy_call = [c for c in mock_server.uid.call_args_list if c[0][0] == "COPY"]
        assert len(copy_call) == 1
        assert copy_call[0][0][2] == "Gmail/All Mail"

    @pytest.mark.asyncio
    async def test_archive_email_no_credentials(self):
        """Test archiving returns error when credentials are missing."""
        t = Tools()
        t.valves.allow_archive = True
        result = await t.archive_email(email_index=1)
        assert "Error" in result and "credentials" in result


class TestSieveTools:
    """Tests for ManageSieve filter management features."""

    @pytest.fixture
    def sieve_tools(self):
        t = Tools()
        t.valves.imap_server = "sieve.example.com"
        t.valves.username = "testuser"
        t.valves.password = "testpass"
        t.valves.manage_sieve_server = ""
        t.valves.manage_sieve_port = 4190
        t.valves.manage_sieve_encryption = EncryptionMode.starttls
        t.valves.manage_sieve_timeout = 30
        return t

    def _make_sieve_mock(self, active="filter1", scripts=None):
        """Create a mock ManageSieve client with script data."""
        client = MagicMock()
        _scripts = scripts or ["filter1", "filter2", "spam_block"]
        client.listscripts.return_value = (active if active else None, _scripts)
        client.getscript.return_value = (
            'require "fileinto";\nif header :contains "Subject" "invoice" {\n  fileinto "Invoices";\n}'
        )
        client.return_value = client
        return client

    @pytest.mark.asyncio
    async def test_list_sieve_scripts_success(self, sieve_tools):
        """Test listing Sieve scripts on the server."""
        mock_client = self._make_sieve_mock(active="filter1", scripts=["filter1", "filter2"])
        with patch("imap_mailbox._try_sievelib_client", MagicMock(return_value=mock_client)):
            result = await sieve_tools.list_sieve_scripts()
        assert "filter1" in result
        assert "filter2" in result
        assert ">>>" in result or "filter1" in result
        assert "active" in result.lower()

    @pytest.mark.asyncio
    async def test_list_sieve_scripts_empty(self, sieve_tools):
        """Test listing when no Sieve scripts exist."""
        mock_client = MagicMock()
        mock_client.listscripts.return_value = (None, [])
        with patch("imap_mailbox._try_sievelib_client", MagicMock(return_value=mock_client)):
            result = await sieve_tools.list_sieve_scripts()
        assert "No Sieve scripts" in result

    @pytest.mark.asyncio
    async def test_list_sieve_scripts_no_sievelib(self):
        """Test error when sievelib is not installed."""
        import imap_mailbox

        original = imap_mailbox._try_sievelib_client
        try:
            imap_mailbox._try_sievelib_client = None
            t = Tools()
            result = await t.list_sieve_scripts()
            assert "sievelib" in result.lower()
        finally:
            imap_mailbox._try_sievelib_client = original

    @pytest.mark.asyncio
    async def test_get_sieve_script_success(self, sieve_tools):
        """Test retrieving a Sieve script by name."""
        mock_client = self._make_sieve_mock()
        with patch("imap_mailbox._try_sievelib_client", MagicMock(return_value=mock_client)):
            result = await sieve_tools.get_sieve_script(name="filter1")
        assert "Sieve Script: filter1" in result
        assert "fileinto" in result

    @pytest.mark.asyncio
    async def test_get_sieve_script_not_found(self, sieve_tools):
        """Test retrieving a non-existent script."""
        mock_client = self._make_sieve_mock()
        with patch("imap_mailbox._try_sievelib_client", MagicMock(return_value=mock_client)):
            result = await sieve_tools.get_sieve_script(name="nonexistent")
        assert "not found" in result.lower()

    @pytest.mark.asyncio
    async def test_get_sieve_script_empty_scripts(self, sieve_tools):
        """Test retrieving a script when none exist."""
        mock_client = MagicMock()
        mock_client.listscripts.return_value = (None, [])
        with patch("imap_mailbox._try_sievelib_client", MagicMock(return_value=mock_client)):
            result = await sieve_tools.get_sieve_script(name="any")
        assert "No Sieve scripts" in result

    @pytest.mark.asyncio
    async def test_create_sieve_script_success(self, sieve_tools):
        """Test creating a new Sieve script."""
        sieve_tools.valves.allow_create_sieve = True
        mock_client = self._make_sieve_mock()
        mock_client.listscripts.return_value = (None, [])  # no scripts yet
        with patch("imap_mailbox._try_sievelib_client", MagicMock(return_value=mock_client)):
            result = await sieve_tools.create_sieve_script(name="auto_filter", content="require 'fileinto';")
        assert "created successfully" in result
        mock_client.putscript.assert_called_once_with("auto_filter", "require 'fileinto';")

    @pytest.mark.asyncio
    async def test_create_sieve_script_already_exists(self, sieve_tools):
        """Test creating a script that already exists."""
        sieve_tools.valves.allow_create_sieve = True
        mock_client = self._make_sieve_mock()
        with patch("imap_mailbox._try_sievelib_client", MagicMock(return_value=mock_client)):
            result = await sieve_tools.create_sieve_script(name="filter1", content="new content")
        assert "already exists" in result

    @pytest.mark.asyncio
    async def test_create_sieve_script_disabled(self, sieve_tools):
        """Test creating a script when create permission is disabled."""
        mock_client = self._make_sieve_mock()
        with patch("imap_mailbox._try_sievelib_client", MagicMock(return_value=mock_client)):
            result = await sieve_tools.create_sieve_script(name="new_script", content="ignore")
        assert "disabled" in result.lower() and "allow_create_sieve" in result

    @pytest.mark.asyncio
    async def test_update_sieve_script_success(self, sieve_tools):
        """Test updating an existing Sieve script."""
        sieve_tools.valves.allow_update_sieve = True
        mock_client = self._make_sieve_mock()
        with patch("imap_mailbox._try_sievelib_client", MagicMock(return_value=mock_client)):
            result = await sieve_tools.update_sieve_script(name="filter1", content="updated content here")
        assert "updated successfully" in result
        mock_client.putscript.assert_called_once_with("filter1", "updated content here")

    @pytest.mark.asyncio
    async def test_update_sieve_script_not_found(self, sieve_tools):
        """Test updating a non-existent script."""
        sieve_tools.valves.allow_update_sieve = True
        mock_client = self._make_sieve_mock()
        with patch("imap_mailbox._try_sievelib_client", MagicMock(return_value=mock_client)):
            result = await sieve_tools.update_sieve_script(name="ghost", content="stuff")
        assert "not found" in result.lower()

    @pytest.mark.asyncio
    async def test_update_sieve_script_disabled(self, sieve_tools):
        """Test updating a script when update permission is disabled."""
        mock_client = self._make_sieve_mock()
        with patch("imap_mailbox._try_sievelib_client", MagicMock(return_value=mock_client)):
            result = await sieve_tools.update_sieve_script(name="x", content="y")
        assert "disabled" in result.lower() and "allow_update_sieve" in result

    @pytest.mark.asyncio
    async def test_delete_sieve_script_success(self, sieve_tools):
        """Test deleting a Sieve script."""
        sieve_tools.valves.allow_delete_sieve = True
        mock_client = self._make_sieve_mock()
        with patch("imap_mailbox._try_sievelib_client", MagicMock(return_value=mock_client)):
            result = await sieve_tools.delete_sieve_script(name="filter2")
        assert "deleted successfully" in result
        mock_client.deletescript.assert_called_once_with("filter2")

    @pytest.mark.asyncio
    async def test_delete_sieve_script_active_deactivates(self, sieve_tools):
        """Test that deleting an active script also deactivates it."""
        sieve_tools.valves.allow_delete_sieve = True
        mock_client = self._make_sieve_mock(active="filter2", scripts=["filter1", "filter2"])
        with patch("imap_mailbox._try_sievelib_client", MagicMock(return_value=mock_client)):
            result = await sieve_tools.delete_sieve_script(name="filter2")
        assert "deleted successfully" in result
        mock_client.deletescript.assert_called_once_with("filter2")
        mock_client.setactive.assert_called_once_with(None)

    @pytest.mark.asyncio
    async def test_delete_sieve_script_not_found(self, sieve_tools):
        """Test deleting a non-existent script."""
        sieve_tools.valves.allow_delete_sieve = True
        mock_client = self._make_sieve_mock()
        with patch("imap_mailbox._try_sievelib_client", MagicMock(return_value=mock_client)):
            result = await sieve_tools.delete_sieve_script(name="ghost_script")
        assert "not found" in result.lower()

    @pytest.mark.asyncio
    async def test_delete_sieve_script_disabled(self, sieve_tools):
        """Test deleting when delete permission is disabled."""
        with patch("imap_mailbox._try_sievelib_client", MagicMock(return_value=MagicMock(return_value=MagicMock()))):
            result = await sieve_tools.delete_sieve_script(name="x")
        assert "disabled" in result.lower() and "allow_delete_sieve" in result

    @pytest.mark.asyncio
    async def test_set_active_sieve_script_success(self, sieve_tools):
        """Test activating a Sieve script."""
        sieve_tools.valves.allow_activate_sieve = True
        mock_client = self._make_sieve_mock()
        mock_client.listscripts.return_value = (None, ["filter1", "filter2"])
        with patch("imap_mailbox._try_sievelib_client", MagicMock(return_value=mock_client)):
            result = await sieve_tools.set_active_sieve_script(name="filter2")
        assert "now active" in result
        mock_client.setactive.assert_called_once_with("filter2")

    @pytest.mark.asyncio
    async def test_set_active_sieve_script_not_found(self, sieve_tools):
        """Test activating a non-existent script."""
        sieve_tools.valves.allow_activate_sieve = True
        mock_client = self._make_sieve_mock()
        with patch("imap_mailbox._try_sievelib_client", MagicMock(return_value=mock_client)):
            result = await sieve_tools.set_active_sieve_script(name="phantom")
        assert "not found" in result.lower()

    @pytest.mark.asyncio
    async def test_set_active_sieve_script_disabled(self, sieve_tools):
        """Test activating when permission is disabled."""
        mock_client = self._make_sieve_mock()
        with patch("imap_mailbox._try_sievelib_client", MagicMock(return_value=mock_client)):
            result = await sieve_tools.set_active_sieve_script(name="x")
        assert "disabled" in result.lower() and "allow_activate_sieve" in result

    @pytest.mark.asyncio
    async def test_deactivate_sieve_script_success(self, sieve_tools):
        """Test deactivating the active Sieve script."""
        sieve_tools.valves.allow_activate_sieve = True
        mock_client = self._make_sieve_mock(active="filter1")
        with patch("imap_mailbox._try_sievelib_client", MagicMock(return_value=mock_client)):
            result = await sieve_tools.deactivate_sieve_script()
        assert "deactivated" in result.lower()
        mock_client.setactive.assert_called_once_with(None)

    @pytest.mark.asyncio
    async def test_deactivate_sieve_script_none_active(self, sieve_tools):
        """Test deactivating when no script is active."""
        sieve_tools.valves.allow_activate_sieve = True
        mock_client = self._make_sieve_mock(active=None)
        with patch("imap_mailbox._try_sievelib_client", MagicMock(return_value=mock_client)):
            result = await sieve_tools.deactivate_sieve_script()
        assert "No Sieve script is currently active" in result

    @pytest.mark.asyncio
    async def test_deactivate_sieve_script_disabled(self, sieve_tools):
        """Test deactivating when permission is disabled."""
        mock_client = self._make_sieve_mock()
        with patch("imap_mailbox._try_sievelib_client", MagicMock(return_value=mock_client)):
            result = await sieve_tools.deactivate_sieve_script()
        assert "disabled" in result.lower() and "allow_activate_sieve" in result

    @pytest.mark.asyncio
    async def test_sieve_no_credentials(self):
        """Test Sieve methods return error when credentials are missing."""
        t = Tools()
        import imap_mailbox

        original = imap_mailbox._try_sievelib_client
        try:
            # Mock to avoid ImportError but still get credential error
            mock_cls = MagicMock()
            imap_mailbox._try_sievelib_client = mock_cls
            result = await t.list_sieve_scripts()
            assert "credentials" in result.lower()
        finally:
            imap_mailbox._try_sievelib_client = original

    @pytest.mark.asyncio
    async def test_sieve_no_server(self, sieve_tools):
        """Test Sieve methods return error when imap_server is empty."""
        sieve_tools.valves.imap_server = ""
        import imap_mailbox

        original = imap_mailbox._try_sievelib_client
        try:
            mock_cls = MagicMock()
            imap_mailbox._try_sievelib_client = mock_cls
            result = await sieve_tools.list_sieve_scripts()
            assert "server" in result.lower()
        finally:
            imap_mailbox._try_sievelib_client = original

    @pytest.mark.asyncio
    async def test_sieve_default_valves(self):
        """Test that Sieve write valves default to False."""
        t = Tools()
        assert t.valves.allow_create_sieve is False
        assert t.valves.allow_update_sieve is False
        assert t.valves.allow_delete_sieve is False
        assert t.valves.allow_activate_sieve is False

    @pytest.mark.asyncio
    async def test_sieve_default_port(self):
        """Test that ManageSieve default port is 4190."""
        t = Tools()
        assert t.valves.manage_sieve_port == 4190
        assert t.valves.manage_sieve_encryption == EncryptionMode.starttls

    @pytest.mark.asyncio
    async def test_sieve_fallback_uses_imap_server(self, sieve_tools):
        """Test that missing manage_sieve_server falls back to imap_server."""
        sieve_tools.valves.imap_server = "imap.example.com"
        sieve_tools.valves.manage_sieve_server = ""
        sieve_tools.valves.allow_create_sieve = True

        mock_client = MagicMock()
        mock_client.listscripts.return_value = (None, [])
        mock_cls = MagicMock(return_value=mock_client)

        import imap_mailbox

        original = imap_mailbox._try_sievelib_client
        try:
            imap_mailbox._try_sievelib_client = mock_cls
            await sieve_tools.create_sieve_script(name="x", content="y")
            mock_cls.assert_called_once_with("imap.example.com", srvport=4190)
        finally:
            imap_mailbox._try_sievelib_client = original


class TestIMAPListEmailsCredentialError:
    """Test list_emails without credentials explicitly set."""

    @pytest.mark.asyncio
    async def test_list_emails_no_username(self):
        """Test list_emails returns error when username is missing (with folder param)."""
        t = Tools()
        t.valves.imap_server = "mail.example.com"
        t.valves.password = "testpass"
        result = await t.list_emails(folder="INBOX", count=5)
        assert "Error" in result and "credentials" in result

    @pytest.mark.asyncio
    async def test_list_emails_no_password(self):
        """Test list_emails returns error when password is missing (with folder param)."""
        t = Tools()
        t.valves.imap_server = "mail.example.com"
        t.valves.username = "testuser"
        result = await t.list_emails(folder="INBOX", count=5)
        assert "Error" in result and "credentials" in result


class TestIMAPSearchUidDataNone:
    """Test search_emails when uid_data[0] is None (server returned None instead of empty)."""

    @pytest.mark.asyncio
    async def test_search_emails_uid_data_none(self, tools):
        """Test search returns not found when server returns None for uid data."""

        def override_uid(cmd, criteria=None, *args, **kwargs):
            if cmd == "search":
                return ("OK", [None])  # Server returns None (not b'' or empty string)
            return ("OK", [b""])

        mock_server = _make_mock_server([], override_uid=override_uid)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.search_emails(query='subject:"test"')
        assert "No emails found" in result


class TestIMAPSearchFreeTextEmpty:
    """Test search_emails free-text search where no emails match client-side filter."""

    @pytest.mark.asyncio
    async def test_search_free_text_no_client_match(self, tools):
        """Test search with free text where IMAP returns results but client filtering excludes all."""
        raw = _make_raw_email(
            "alice@example.com", "bob@example.com", "Hello World", "This email does not contain the word xyz"
        )
        emails = [(raw, "1")]
        mock_server = _make_mock_server(emails)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.search_emails(query="xyznotfoundxyz", count=10)
        assert "No emails found" in result


class TestIMAPReadInboxEmailNoCredentials:
    """Test read_inbox_email returns error when credentials are missing."""

    @pytest.mark.asyncio
    async def test_read_inbox_email_no_credentials(self):
        """Test read_inbox_email returns error when credentials are missing (guard passes)."""
        t = Tools()
        t.valves.allow_list_inbox = True  # Pass the access guard
        # No username/password set
        result = await t.read_inbox_email(email_index=1)
        assert "Error" in result and "credentials" in result

    @pytest.mark.asyncio
    async def test_read_inbox_email_no_server(self):
        """Test read_inbox_email returns error when imap_server is not set."""
        t = Tools()
        t.valves.username = "testuser"
        t.valves.password = "testpass"
        t.valves.allow_list_inbox = True
        result = await t.read_inbox_email(email_index=1)
        assert "Error" in result and "server" in result


class TestIMAPListEmailsFetchError:
    """Test list/read error handling for individual fetch failures."""

    @pytest.mark.asyncio
    async def test_list_emails_fetch_error(self, tools):
        """Test that list_emails handles individual fetch failures gracefully."""

        def override_uid(cmd, criteria=None, *args, **kwargs):
            if cmd == "search":
                return ("OK", b"1 2")
            elif cmd == "fetch":
                raise _IMAP_EXCEPTION("FETCH command failed: [ALERT] Internal error")
            return ("OK", [b""])

        mock_server = _make_mock_server([], override_uid=override_uid)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.list_emails(folder="INBOX", count=10)
        # Should contain error messages for the failed UIDs
        assert "Error" in result


class TestIMAPInternalHelpersNoCredentials:
    """Test internal helper methods return error when credentials are missing."""

    @pytest.mark.asyncio
    async def test_list_folder_emails_no_credentials(self, tools):
        """Test _list_folder_emails returns error when credentials are missing."""
        t = Tools()
        result = await t._list_folder_emails("INBOX", count=10)
        assert "Error" in result and "credentials" in result

    @pytest.mark.asyncio
    async def test_read_folder_email_no_credentials(self, tools):
        """Test _read_folder_email returns error when credentials are missing."""
        t = Tools()
        result = await t._read_folder_email(1, "INBOX")
        assert "Error" in result and "credentials" in result


class TestSieveConnectionErrors:
    """Test Sieve exception handling during operations (not just connection time)."""

    @pytest.mark.asyncio
    async def test_create_sieve_script_connection_error(self, tools):
        """Test create_sieve_script returns error when sievelib client.connect() raises."""
        tools.valves.allow_create_sieve = True
        tools.valves.imap_server = "sieve.example.com"
        tools.valves.username = "u"
        tools.valves.password = "p"

        mock_client = MagicMock()
        mock_client.connect.side_effect = Exception("authentication failed")
        mock_cls = MagicMock(return_value=mock_client)

        import imap_mailbox

        original = imap_mailbox._try_sievelib_client
        try:
            imap_mailbox._try_sievelib_client = mock_cls
            result = await tools.create_sieve_script(name="test", content='fileinto "test";')
            assert "Error" in result and "ManageSieve" in result
        finally:
            imap_mailbox._try_sievelib_client = original

    @pytest.mark.asyncio
    async def test_create_sieve_script_put_error(self, tools):
        """Test create_sieve_script handles putscript() exception."""
        tools.valves.allow_create_sieve = True
        tools.valves.imap_server = "sieve.example.com"
        tools.valves.username = "u"
        tools.valves.password = "p"

        mock_client = MagicMock()
        mock_client.listscripts.return_value = (None, ["existing"])
        mock_client.putscript.side_effect = Exception("server error")

        mock_cls = MagicMock(return_value=mock_client)

        import imap_mailbox

        original = imap_mailbox._try_sievelib_client
        try:
            imap_mailbox._try_sievelib_client = mock_cls
            result = await tools.create_sieve_script(name="new", content="discard;")
            assert "Error" in result and "creating" in result.lower()
        finally:
            imap_mailbox._try_sievelib_client = original

    @pytest.mark.asyncio
    async def test_get_sieve_script_list_error(self, tools):
        """Test get_sieve_script handles listscripts() exception."""
        tools.valves.imap_server = "sieve.example.com"
        tools.valves.username = "u"
        tools.valves.password = "p"

        mock_client = MagicMock()
        mock_client.listscripts.side_effect = Exception("connection reset")

        mock_cls = MagicMock(return_value=mock_client)

        import imap_mailbox

        original = imap_mailbox._try_sievelib_client
        try:
            imap_mailbox._try_sievelib_client = mock_cls
            result = await tools.get_sieve_script(name="x")
            assert "Error" in result and "retrieving" in result.lower()
        finally:
            imap_mailbox._try_sievelib_client = original


class TestIMAPListEmailsAttachmentDisplay:
    """Test attachment info display in list_emails output."""

    @pytest.mark.asyncio
    async def test_list_emails_with_attachments_shows_count(self, tools):
        """Test that list_emails shows attachment count when emails have attachments."""
        # Create a multipart email with attachment
        email_bytes = _make_raw_email_with_attachment(
            "sender@example.com", "user@example.com", "Document Attached", "Please see the attached file."
        )
        emails = [(email_bytes, "1")]
        mock_server = _make_mock_server(emails)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.list_emails(folder="INBOX", count=5)
        assert "attachment" in result and "1" in result


class TestIMAPSearchWithAttachments:
    """Test attachment info display in search_emails output."""

    @pytest.mark.asyncio
    async def test_search_emails_with_attachments_shows_count(self, tools):
        """Test that search_emails shows attachment count when emails have attachments."""
        email_bytes = _make_raw_email_with_attachment(
            "sender@example.com", "user@example.com", "Invoice Attached", "Invoice attached for your review."
        )
        emails = [(email_bytes, "1")]
        mock_server = _make_mock_server(emails)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.search_emails(query="Invoice", count=5, folder="INBOX")
        assert "attachment" in result.lower() and "1" in result


class TestIMAPGetEmailCountServer:
    """Test get_email_count credential edge cases."""

    @pytest.mark.asyncio
    async def test_get_email_count_with_credentials_no_server(self):
        """Test get_email_count returns error when imap_server is not set but credentials are."""
        t = Tools()
        t.valves.username = "testuser"
        t.valves.password = "testpass"
        result = await t.get_email_count()
        assert "Error" in result and "server" in result


class TestGenericExceptionEmailCount:
    """Test generic exception in get_email_count (lines 835-836)."""

    @pytest.mark.asyncio
    async def test_get_email_count_generic_exception(self):
        """Test get_email_count catches generic Exception (lines 835-836)."""
        t = Tools()
        t.valves.imap_server = "mail.example.com"
        t.valves.username = "testuser"
        t.valves.password = "testpass"

        with patch("imap_mailbox._IMAP_EXCEPTION", OSError):
            mock_server = MagicMock()
            mock_server.login.side_effect = NotImplementedError("Generic error")
            with patch("imaplib.IMAP4_SSL", return_value=mock_server):
                result = await t.get_email_count()
            assert "Error checking mailbox" in result


class TestDeleteEmailEmptyMailbox:
    """Test delete_email when mailbox is empty (lines 859-860)."""

    @pytest.mark.asyncio
    async def test_delete_email_empty_mailbox(self):
        """Test delete_email when mailbox is empty (lines 859-860)."""
        t = Tools()
        t.valves.imap_server = "mail.example.com"
        t.valves.username = "testuser"
        t.valves.password = "testpass"
        t.valves.allow_delete_single = True

        mock_server = MagicMock()
        mock_server.login.return_value = ("OK", [b"Login successful"])
        mock_server.select.return_value = ("OK", [b"0 Messages"])
        mock_server.close.return_value = None
        mock_server.expunge.return_value = ("OK", [b"EXPUNGE"])

        def uid_side_effect(cmd, *args, **kwargs):
            if cmd == "search":
                return ("OK", [b""])
            return ("OK", [b""])

        mock_server.uid.side_effect = uid_side_effect

        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await t.delete_email(email_index=1)
        assert "empty" in result.lower() or "Nothing to delete" in result


class TestIMAPSearchNoCredentials:
    """Test search_emails without credentials."""

    @pytest.mark.asyncio
    async def test_search_emails_no_credentials(self):
        """Test search_emails returns error when credentials are not set."""
        t = Tools()
        result = await t.search_emails(query="test", count=10)
        assert "Error" in result and "credentials" in result

    @pytest.mark.asyncio
    async def test_search_emails_no_server(self):
        """Test search_emails returns error when imap_server is not set."""
        t = Tools()
        t.valves.username = "testuser"
        t.valves.password = "testpass"
        result = await t.search_emails(query="test", count=10)
        assert "Error" in result and "server" in result


class TestIMAPDeleteNoCredentials:
    """Test delete_email credentials edge case."""

    @pytest.mark.asyncio
    async def test_delete_email_no_server(self):
        """Test delete_email returns server error when imap_server not set."""
        t = Tools()
        t.valves.allow_delete_single = True
        t.valves.username = "testuser"
        t.valves.password = "testpass"
        result = await t.delete_email(email_index=1)
        assert "Error" in result and "server" in result


class TestIMAPListSpecialFolders:
    """Test accessing special folders returns errors when not enabled."""

    @pytest.mark.asyncio
    async def test_list_sent_emails_disabled(self):
        """Test list_sent_emails returns access denied when not enabled."""
        t = Tools()
        result = await t.list_sent_emails(count=5)
        assert "disabled" in result.lower()

    @pytest.mark.asyncio
    async def test_read_sent_email_disabled(self):
        """Test read_sent_email returns access denied when not enabled."""
        t = Tools()
        result = await t.read_sent_email(email_index=1)
        assert "disabled" in result.lower()

    @pytest.mark.asyncio
    async def test_list_trash_emails_disabled(self):
        """Test list_trash_emails returns access denied when not enabled."""
        t = Tools()
        result = await t.list_trash_emails(count=5)
        assert "disabled" in result.lower()

    @pytest.mark.asyncio
    async def test_read_trash_email_disabled(self):
        """Test read_trash_email returns access denied when not enabled."""
        t = Tools()
        result = await t.read_trash_email(email_index=1)
        assert "disabled" in result.lower()


class TestSieveOtherExceptions:
    """Test remaining Sieve exception paths."""

    @pytest.mark.asyncio
    async def test_list_sieve_scripts_operation_error(self, tools):
        """Test list_sieve_scripts handles listscripts() exception."""
        tools.valves.imap_server = "sieve.example.com"
        tools.valves.username = "u"
        tools.valves.password = "p"

        mock_client = MagicMock()
        mock_client.listscripts.side_effect = Exception("list failed")
        mock_cls = MagicMock(return_value=mock_client)

        import imap_mailbox

        original = imap_mailbox._try_sievelib_client
        try:
            imap_mailbox._try_sievelib_client = mock_cls
            result = await tools.list_sieve_scripts()
            assert "Error" in result and "listing" in result.lower()
        finally:
            imap_mailbox._try_sievelib_client = original

    @pytest.mark.asyncio
    async def test_update_sieve_script_no_scripts(self, tools):
        """Test update_sieve_script returns error when no scripts exist."""
        tools.valves.allow_update_sieve = True
        tools.valves.imap_server = "sieve.example.com"
        tools.valves.username = "u"
        tools.valves.password = "p"

        mock_client = MagicMock()
        mock_client.listscripts.return_value = (None, [])

        mock_cls = MagicMock(return_value=mock_client)

        import imap_mailbox

        original = imap_mailbox._try_sievelib_client
        try:
            imap_mailbox._try_sievelib_client = mock_cls
            result = await tools.update_sieve_script(name="x", content="y")
            assert "No Sieve scripts" in result
        finally:
            imap_mailbox._try_sievelib_client = original

    @pytest.mark.asyncio
    async def test_update_sieve_script_put_error(self, tools):
        """Test update_sieve_script handles putscript() exception."""
        tools.valves.allow_update_sieve = True
        tools.valves.imap_server = "sieve.example.com"
        tools.valves.username = "u"
        tools.valves.password = "p"

        mock_client = MagicMock()
        mock_client.listscripts.return_value = (None, ["existing"])
        mock_client.putscript.side_effect = Exception("write failed")

        mock_cls = MagicMock(return_value=mock_client)

        import imap_mailbox

        original = imap_mailbox._try_sievelib_client
        try:
            imap_mailbox._try_sievelib_client = mock_cls
            result = await tools.update_sieve_script(name="existing", content="new content")
            assert "Error" in result and "updating" in result.lower()
        finally:
            imap_mailbox._try_sievelib_client = original

    @pytest.mark.asyncio
    async def test_delete_sieve_script_empty(self, tools):
        """Test delete_sieve_script when no scripts exist."""
        tools.valves.allow_delete_sieve = True
        tools.valves.imap_server = "sieve.example.com"
        tools.valves.username = "u"
        tools.valves.password = "p"

        mock_client = MagicMock()
        mock_client.listscripts.return_value = (None, [])

        mock_cls = MagicMock(return_value=mock_client)

        import imap_mailbox

        original = imap_mailbox._try_sievelib_client
        try:
            imap_mailbox._try_sievelib_client = mock_cls
            result = await tools.delete_sieve_script(name="nonexistent")
            assert "No Sieve scripts" in result
        finally:
            imap_mailbox._try_sievelib_client = original

    @pytest.mark.asyncio
    async def test_delete_sieve_script_error(self, tools):
        """Test delete_sieve_script handles deletescript() exception."""
        tools.valves.allow_delete_sieve = True
        tools.valves.imap_server = "sieve.example.com"
        tools.valves.username = "u"
        tools.valves.password = "p"

        mock_client = MagicMock()
        mock_client.listscripts.return_value = (None, ["to_delete"])
        mock_client.deletescript.side_effect = Exception("delete failed")

        mock_cls = MagicMock(return_value=mock_client)

        import imap_mailbox

        original = imap_mailbox._try_sievelib_client
        try:
            imap_mailbox._try_sievelib_client = mock_cls
            result = await tools.delete_sieve_script(name="to_delete")
            assert "Error" in result and "deleting" in result.lower()
        finally:
            imap_mailbox._try_sievelib_client = original

    @pytest.mark.asyncio
    async def test_set_active_sieve_script_empty(self, tools):
        """Test set_active_sieve_script when no scripts exist."""
        tools.valves.allow_activate_sieve = True
        tools.valves.imap_server = "sieve.example.com"
        tools.valves.username = "u"
        tools.valves.password = "p"

        mock_client = MagicMock()
        mock_client.listscripts.return_value = (None, [])

        mock_cls = MagicMock(return_value=mock_client)

        import imap_mailbox

        original = imap_mailbox._try_sievelib_client
        try:
            imap_mailbox._try_sievelib_client = mock_cls
            result = await tools.set_active_sieve_script(name="any")
            assert "No Sieve scripts" in result
        finally:
            imap_mailbox._try_sievelib_client = original

    @pytest.mark.asyncio
    async def test_set_active_sieve_script_error(self, tools):
        """Test set_active_sieve_script handles setactive() exception."""
        tools.valves.allow_activate_sieve = True
        tools.valves.imap_server = "sieve.example.com"
        tools.valves.username = "u"
        tools.valves.password = "p"

        mock_client = MagicMock()
        mock_client.listscripts.return_value = (None, ["active1"])
        mock_client.setactive.side_effect = Exception("activate failed")

        mock_cls = MagicMock(return_value=mock_client)

        import imap_mailbox

        original = imap_mailbox._try_sievelib_client
        try:
            imap_mailbox._try_sievelib_client = mock_cls
            result = await tools.set_active_sieve_script(name="active1")
            assert "Error" in result and "activating" in result.lower()
        finally:
            imap_mailbox._try_sievelib_client = original

    @pytest.mark.asyncio
    async def test_deactivate_sieve_script_error(self, tools):
        """Test deactivate_sieve_script handles setactive() exception."""
        tools.valves.allow_activate_sieve = True
        tools.valves.imap_server = "sieve.example.com"
        tools.valves.username = "u"
        tools.valves.password = "p"

        mock_client = MagicMock()
        mock_client.listscripts.return_value = ("active1", ["active1"])
        mock_client.setactive.side_effect = Exception("deactivate failed")

        mock_cls = MagicMock(return_value=mock_client)

        import imap_mailbox

        original = imap_mailbox._try_sievelib_client
        try:
            imap_mailbox._try_sievelib_client = mock_cls
            result = await tools.deactivate_sieve_script()
            assert "Error" in result and "deactivating" in result.lower()
        finally:
            imap_mailbox._try_sievelib_client = original


class TestSieveMissingClientGuards:
    """Test Sieve guards that fire when _try_sievelib_client returns error string."""

    @pytest.mark.asyncio
    async def test_get_sieve_script_no_client(self, tools):
        """Test get_sieve_script returns early when no sievelib client."""
        tools.valves.imap_server = "s.example.com"
        tools.valves.username = "u"
        tools.valves.password = "p"

        import imap_mailbox

        original = imap_mailbox._try_sievelib_client
        try:
            imap_mailbox._try_sievelib_client = None
            result = await tools.get_sieve_script(name="x")
            assert "Error" in result and "sievelib" in result.lower()
        finally:
            imap_mailbox._try_sievelib_client = original

    @pytest.mark.asyncio
    async def test_update_sieve_script_no_client(self, tools):
        """Test update_sieve_script returns early when no sievelib client."""
        tools.valves.allow_update_sieve = True
        tools.valves.imap_server = "s.example.com"
        tools.valves.username = "u"
        tools.valves.password = "p"

        import imap_mailbox

        original = imap_mailbox._try_sievelib_client
        try:
            imap_mailbox._try_sievelib_client = None
            result = await tools.update_sieve_script(name="x", content="y")
            assert "Error" in result and "sievelib" in result.lower()
        finally:
            imap_mailbox._try_sievelib_client = original

    @pytest.mark.asyncio
    async def test_delete_sieve_script_no_client(self, tools):
        """Test delete_sieve_script returns early when no sievelib client."""
        tools.valves.allow_delete_sieve = True
        tools.valves.imap_server = "s.example.com"
        tools.valves.username = "u"
        tools.valves.password = "p"

        import imap_mailbox

        original = imap_mailbox._try_sievelib_client
        try:
            imap_mailbox._try_sievelib_client = None
            result = await tools.delete_sieve_script(name="x")
            assert "Error" in result and "sievelib" in result.lower()
        finally:
            imap_mailbox._try_sievelib_client = original

    @pytest.mark.asyncio
    async def test_set_active_sieve_script_no_client(self, tools):
        """Test set_active_sieve_script returns early when no sievelib client."""
        tools.valves.allow_activate_sieve = True
        tools.valves.imap_server = "s.example.com"
        tools.valves.username = "u"
        tools.valves.password = "p"

        import imap_mailbox

        original = imap_mailbox._try_sievelib_client
        try:
            imap_mailbox._try_sievelib_client = None
            result = await tools.set_active_sieve_script(name="x")
            assert "Error" in result and "sievelib" in result.lower()
        finally:
            imap_mailbox._try_sievelib_client = original

    @pytest.mark.asyncio
    async def test_deactivate_sieve_script_no_client(self, tools):
        """Test deactivate_sieve_script returns early when no sievelib client."""
        tools.valves.allow_activate_sieve = True
        tools.valves.imap_server = "s.example.com"
        tools.valves.username = "u"
        tools.valves.password = "p"

        import imap_mailbox

        original = imap_mailbox._try_sievelib_client
        try:
            imap_mailbox._try_sievelib_client = None
            result = await tools.deactivate_sieve_script()
            assert "Error" in result and "sievelib" in result.lower()
        finally:
            imap_mailbox._try_sievelib_client = original


class TestIMAPEmptyMailboxPaths:
    """Test empty mailbox edge cases that hit early-return guards."""

    @pytest.mark.asyncio
    async def test_read_email_empty_mailbox(self, tools):
        """Test read_email returns early when mailbox is empty (uid_map is empty dict)."""

        def override_uid(cmd, criteria=None, *args, **kwargs):
            if cmd == "search":
                # Return proper IMAP response with empty results
                return ("OK", [b""])
            # Never reached since uid_map is empty
            return ("OK", [b"", b""])

        mock_server = _make_mock_server([], override_uid=override_uid)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.read_email(email_index=1)
        assert "empty" in result.lower()

    @pytest.mark.asyncio
    async def test_search_emails_no_credentials(self):
        """Test search_emails returns error without credentials."""
        t = Tools()
        t.valves.imap_server = "mail.example.com"
        result = await t.search_emails(query="test", count=5)
        assert "Error" in result and "credentials" in result

    @pytest.mark.asyncio
    async def test_delete_email_no_server(self):
        """Test delete_email returns server error when imap_server not configured."""
        t = Tools()
        t.valves.allow_delete_single = True
        t.valves.username = "u"
        t.valves.password = "p"
        result = await t.delete_email(email_index=1)
        assert "Error" in result and "server" in result

    @pytest.mark.asyncio
    async def test_delete_all_emails_no_credentials(self):
        """Test delete_all_emails returns error without credentials."""
        t = Tools()
        t.valves.allow_delete_all = True
        t.valves.imap_server = "mail.example.com"
        result = await t.delete_all_emails()
        assert "Error" in result and "credentials" in result

    @pytest.mark.asyncio
    async def test_get_email_count_generic_exception(self):
        """Test get_email_count handles non-IMAP error after login."""
        tools = Tools()
        tools.valves.username = "u"
        tools.valves.password = "p"
        tools.valves.imap_server = "mail.example.com"

        def mock_login_side_effect(username, password):
            raise RuntimeError("select failed")

        mock_server = MagicMock()
        mock_server.login = mock_login_side_effect

        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.get_email_count()
        # Should get exception handling path
        assert "Error" in result


class TestIMAPUidDataNonePath:
    """Test edge cases where uid_data[0] is None."""

    @pytest.mark.asyncio
    async def test_refresh_uid_index_uid_data_none(self, tools):
        """Test _refresh_uid_index returns empty dict when uid_data[0] is None."""

        def override_uid(cmd, criteria=None, *args, **kwargs):
            if cmd == "search":
                return ("OK", [None])  # Server returns None instead of empty list
            return ("OK", [b"", b""])

        mock_server = _make_mock_server([], override_uid=override_uid)
        from imap_mailbox import Tools as IMAPTools

        t = IMAPTools()
        t.valves.username = "u"
        t.valves.password = "p"
        t.valves.imap_server = "mail.example.com"

        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            conn = t._connect()
            uid_map = t._refresh_uid_index(conn)
            conn.close()
        assert uid_map == {}

    @pytest.mark.asyncio
    async def test_list_emails_non_imap_fetch_error(self, tools):
        """Test list_emails handles non-IMAPException fetch failures (inner exception handler at 527-528)."""

        def override_uid(cmd, criteria=None, *args, **kwargs):
            if cmd == "search":
                return ("OK", b"1")
            elif cmd == "fetch":
                raise RuntimeError("unexpected error, not IMAP exception")
            return ("OK", [b"", b""])

        mock_server = _make_mock_server([], override_uid=override_uid)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.list_emails(folder="INBOX", count=10)
        # Should show error for the UID but not crash
        assert "Error" in result or "INBOX" in result

    @pytest.mark.asyncio
    async def test_search_emails_free_text_max_count(self, tools):
        """Test search_emails stops fetching after hitting count limit in free-text search (line 734)."""
        raw1 = _make_raw_email("a@example.com", "b@example.com", "Match One", "contains word")
        raw2 = _make_raw_email("c@example.com", "d@example.com", "Match Two", "contains word")
        raw3 = _make_raw_email("e@example.com", "f@example.com", "Match Three", "contains word")
        emails = [(raw1, "1"), (raw2, "2"), (raw3, "3")]
        mock_server = _make_mock_server(emails)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.search_emails(query="word", count=2, folder="INBOX")
        # Should find 2 matches (count limit), not all 3
        assert "2 email" in result or "2 email" in result or "Found 2" in result


class TestIMAPGetEmailCountException:
    """Test get_email_count exception handling."""

    @pytest.mark.asyncio
    async def test_get_email_count_server_error(self):
        """Test get_email_count handles runtime error during server operation."""
        t = Tools()
        t.valves.username = "u"
        t.valves.password = "p"
        t.valves.imap_server = "mail.example.com"

        mock_server = MagicMock()
        mock_server.login.return_value = None
        mock_server.select.side_effect = RuntimeError("connection dropped")

        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await t.get_email_count()
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_get_email_count_generic_exception(self):
        """Test get_email_count with non-IMAP generic exception (lines 835-836)."""
        t = Tools()
        t.valves.username = "u"
        t.valves.password = "p"
        t.valves.imap_server = "mail.example.com"

        mock_server = MagicMock()
        mock_server.login.return_value = ("OK", None)
        mock_server.uid.side_effect = AttributeError("broken connection")

        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await t.get_email_count()
        assert "Error" in result


class TestIMAPEmptyRawDataFetch:
    """Test IMAP email parsing when raw_data is empty or malformed."""

    @pytest.mark.asyncio
    async def test_list_emails_empty_raw_data(self, tools):
        """Test list_emails handles exception during UID fetch (lines 553-567)."""
        mock_server = MagicMock()

        def uid_side_effect(cmd, *args, **kwargs):
            if cmd == "search":
                return ("OK", [b"101"])
            elif cmd == "fetch":
                # Return a malformed response where raw_data[0] has no index 1
                # This triggers the except block at line 553
                return ("OK", [b"101 (FETCH)"])
            return ("OK", [b"101"])

        mock_server.uid.side_effect = uid_side_effect
        mock_server.login.return_value = ("OK", None)
        mock_server.examine.return_value = ("OK", [b"1"])

        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.list_emails(count=5, folder="INBOX")
        assert "Error reading message" in result

    @pytest.mark.asyncio
    async def test_read_folder_email_attachments_shown(self, tools):
        """Test _read_folder_email shows attachment info when has_attachments=True (line 1160)."""
        raw_with_attach = _make_raw_email_with_attachment("a@b.com", "c@d.com", "Doc Attached", "Body")
        mock_server = MagicMock()

        def uid_side_effect(cmd, *args, **kwargs):
            if cmd == "search":
                return ("OK", [b"42"])
            elif cmd == "fetch":
                return ("OK", [(b"42 (UID 42)", raw_with_attach)])
            return ("OK", [b"42"])

        mock_server.uid.side_effect = uid_side_effect
        mock_server.login.return_value = ("OK", None)
        mock_server.select.return_value = ("OK", [b"1"])

        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools._read_folder_email(1, "INBOX")
        assert "Attachments:" in result or "Attachments" in result


class TestIMAPSearchExceptionPaths:
    """Test IMAP search_emails error handling during fetch loop."""

    @pytest.mark.asyncio
    async def test_search_emails_free_text_fetch_exception(self, tools):
        """Test search_emails free-text fallback where one email fails to fetch (lines 770-771)."""
        raw_match = _make_raw_email("a@b.com", "c@d.com", "Match Subject", "Body text")
        raw_no_match = _make_raw_email("x@y.com", "z@w.com", "No Match", "completely different content")
        mock_server = MagicMock()

        fetch_count = [0]

        def uid_side_effect(cmd, *args, **kwargs):
            nonlocal fetch_count
            if cmd == "search":
                return ("OK", [b"1"])
            elif cmd == "fetch":
                fetch_count[0] += 1
                if fetch_count[0] == 1:
                    return ("OK", [(b"1 IMAP2 UID 10", raw_match)])
                else:
                    raise _IMAP_EXCEPTION("fetch error")
            return ("OK", [raw_no_match])

        mock_server.uid.side_effect = uid_side_effect
        mock_server.login.return_value = ("OK", None)
        mock_server.select.return_value = ("OK", [b"1"])

        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.search_emails(query="body", count=5, folder="INBOX")
        assert "email" in result.lower()


class TestIMAPReadEmailCredentials:
    """Test read_email missing credentials guard paths."""

    @pytest.mark.asyncio
    async def test_read_email_no_username(self):
        """Test read_email returns error when username not configured (line 621)."""
        t = Tools()
        t.valves.username = ""
        t.valves.password = "p"
        t.valves.imap_server = "mail.example.com"
        result = await t.read_email(email_index=1)
        assert "credentials" in result.lower()

    @pytest.mark.asyncio
    async def test_read_email_no_server(self):
        """Test read_email returns error when server not configured (line 623)."""
        t = Tools()
        t.valves.username = "u"
        t.valves.password = "p"
        result = await t.read_email(email_index=1)
        assert "server is not configured" in result


class TestIMAPSearchCandidateException:
    """Test search_emails candidate email fetch exception path (lines 782-783)."""

    @pytest.mark.asyncio
    async def test_search_emails_candidate_fetch_exception(self):
        """Test search_emails where uid search returns but fetch fails for all candidates."""
        t = Tools()
        t.valves.username = "u"
        t.valves.password = "p"
        t.valves.imap_server = "mail.example.com"
        mock_server = MagicMock()

        def uid_side_effect(cmd, *args, **kwargs):
            if cmd == "search":
                return ("OK", [b"1"])
            else:
                raise _IMAP_EXCEPTION("fetch failed for all candidates")

        mock_server.uid.side_effect = uid_side_effect
        mock_server.login.return_value = ("OK", None)
        mock_server.select.return_value = ("OK", [b"1"])

        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await t.search_emails(query="anything", count=5)
        assert "email" in result.lower()


class TestIMAPListFolderException:
    """Test _list_folder_emails exception handling."""

    @pytest.mark.asyncio
    async def test_list_folder_email_inner_fetch_exception(self):
        """Test _list_folder_emails where individual UID fetch fails (lines 1084-1098)."""
        t = Tools()
        t.valves.username = "u"
        t.valves.password = "p"
        t.valves.imap_server = "mail.example.com"

        mock_server = MagicMock()

        def uid_side_effect(cmd, *args, **kwargs):
            if cmd == "search":
                return ("OK", [b"1 2 3"])
            else:
                raise _IMAP_EXCEPTION("fetch error during list")

        mock_server.uid.side_effect = uid_side_effect
        mock_server.login.return_value = ("OK", None)
        mock_server.select.return_value = ("OK", [b"3"])

        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await t._list_folder_emails(folder="CustomFolder", count=5)
        assert "Error reading message" in result


class TestSieveImplicitTLS:
    """Test ManageSieve with implicit TLS encryption mode (lines 153-158)."""

    @pytest.fixture
    def sieve_tools_implicit(self):
        t = Tools()
        t.valves.imap_server = "sieve.example.com"
        t.valves.username = "testuser"
        t.valves.password = "testpass"
        t.valves.manage_sieve_server = ""
        t.valves.manage_sieve_port = 4190
        t.valves.manage_sieve_encryption = EncryptionMode.implicit
        t.valves.manage_sieve_timeout = 30
        return t

    @pytest.mark.asyncio
    async def test_list_sieve_scripts_implicit_tls(self, sieve_tools_implicit):
        """Test Sieve connect uses implicit TLS (ssl=True, starttls=False) at lines 153-158."""
        mock_client = MagicMock()
        mock_client.listscripts.return_value = ("active1", ["script1", "script2"])
        with patch("imap_mailbox._try_sievelib_client", MagicMock(return_value=mock_client)):
            await sieve_tools_implicit.list_sieve_scripts()
        mock_client.connect.assert_called_once_with("testuser", "testpass", ssl=True, starttls=False)

    @pytest.mark.asyncio
    async def test_get_sieve_script_implicit_tls(self, sieve_tools_implicit):
        """Test get_sieve_script works with implicit TLS connection."""
        mock_client = MagicMock()
        mock_client.listscripts.return_value = ("active1", ["script1"])
        mock_client.getscript.return_value = "require 'fileinto';\nif header :contains ..."
        with patch("imap_mailbox._try_sievelib_client", MagicMock(return_value=mock_client)):
            result = await sieve_tools_implicit.get_sieve_script(name="script1")
        mock_client.connect.assert_called_once_with("testuser", "testpass", ssl=True, starttls=False)
        assert "require" in result

    @pytest.mark.asyncio
    async def test_manage_sieve_connect_implicit_tls_error(self, sieve_tools_implicit):
        """Test ManageSieve implicit TLS connect raises exception → error string."""
        mock_client = MagicMock()
        mock_client.connect.side_effect = OSError("TLS handshake failed")

        class FakeTrySievelib:
            def __init__(self, server, srvport=4190):
                self.server = server
                self.srvport = srvport

            def __call__(self):
                return mock_client

        with patch("imap_mailbox._try_sievelib_client", FakeTrySievelib):
            result = sieve_tools_implicit._manage_sieve_connect()
        assert isinstance(result, str) and "ManageSieve Error" in result


class TestIMAPDecodeMIMECharsetErrors:
    """Test _decode_mime_header charset decode failure paths (lines 357-358)."""

    @pytest.mark.asyncio
    async def test_decode_mime_header_lookup_error(self, tools):
        """Test _decode_mime_header with invalid charset triggers LookupError fallback (lines 357-358)."""
        # create_header_value with an unusual charset that triggers LookupError
        result = tools._decode_mime_header("=?invalidx?Q?testvalue?=")
        assert "testvalue" in result or "invalidx" in result.lower()

    @pytest.mark.asyncio
    async def test_decode_mime_header_unicode_decode_error(self, tools):
        """Test _decode_mime_header with bytes that fail in declared charset (lines 357-358)."""
        result = tools._decode_mime_header("=?iso-8859-1?Q?=E9test?=")
        assert "test" in result.lower() or "E9" in result


class TestIMAPGetBodyCharsetErrors:
    """Test _get_email_body charset decode error paths (lines 377-378, 385-386)."""

    @pytest.mark.asyncio
    async def test_get_email_body_multipart_lookup_error(self, tools):
        """Test multipart body with LookupError/UnicodeDecodeError during decode (lines 377-378)."""
        from email.mime.multipart import MIMEMultipart

        class BadPart(MIMEText):
            def get_content_charset(self):
                return "nonexistent-charset-xyz-123"

            def get_payload(self, decode=False):
                if decode:
                    return b"\x80\x81\x82\xff"
                return "inner"

        msg = MIMEMultipart()
        msg.attach(BadPart("inner"))
        tools._get_email_body(msg)

    @pytest.mark.asyncio
    async def test_get_email_body_non_multipart_decode_error(self, tools):
        """Test non-multipart body extraction with charset decode error (lines 385-386)."""
        msg = email.message_from_string("Content-Type: text/plain; charset=nonexistent-xyz-123\r\n\r\n")

        def mock_get_payload(decode=False):
            if decode:
                return b"\xff\xfe\x00\x01"
            return None

        msg.get_payload = mock_get_payload
        result = tools._get_email_body(msg)
        # Should handle decode error gracefully without crashing
        assert isinstance(result, str)


class TestIMAPDeleteCredentialsException:
    """Test delete_email missing credentials with generic exception path."""

    @pytest.mark.asyncio
    async def test_delete_email_missing_credentials_generic(self, tools):
        """Test delete_email when username is empty → generic Exception catch (lines 846-848)."""
        t = Tools()
        t.valves.allow_delete_single = True
        t.valves.username = ""
        t.valves.password = "p"
        t.valves.imap_server = "mail.example.com"
        mock_server = MagicMock()
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await t.delete_email(1)
        assert "credentials" in result.lower()


class TestIMAPSearchCombinedFilters:
    """Test search_emails combined filter edge cases."""

    @pytest.mark.asyncio
    async def test_search_emails_free_text_no_results(self, tools):
        """Test search_emails with free-text fallback returns 'No emails found'."""
        raw = _make_raw_email("sender@x.com", "recv@y.com", "Unrelated Subject", "completely different content")
        mock_server = MagicMock()

        def uid_side_effect(cmd, *args, **kwargs):
            if cmd == "search":
                return ("OK", [b"1"])
            else:
                return ("OK", [(b"1 IMAP2 UID 10", raw)])

        mock_server.uid.side_effect = uid_side_effect
        mock_server.login.return_value = ("OK", None)
        mock_server.select.return_value = ("OK", [b"1"])

        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.search_emails(query="totally-missing-keyword-xyz-999", count=5)
        assert "No emails found" in result
