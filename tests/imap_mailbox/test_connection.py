"""Auto-generated test module."""

from unittest.mock import patch

import pytest

from imap_mailbox import EncryptionMode

from .conftest import _make_mock_server, _make_raw_email


class TestNonSSLConnection:
    """Test non-SSL connection path."""

    @pytest.mark.asyncio
    async def test_list_emails_non_ssl(self, tools):
        """Test that encryption_method='starttls' connects via imaplib.IMAP4 with STARTTLS."""
        tools.valves.encryption_method = EncryptionMode.starttls
        tools.valves.imap_port = 143
        raw = _make_raw_email("sender@test.com", "recv@test.com", "Hello", "Body")
        emails = [(raw, "1")]
        mock_server = _make_mock_server(emails)
        with (
            patch("imaplib.IMAP4", return_value=mock_server) as mock_imap4,
            patch("imaplib.IMAP4_SSL"),
        ):
            result = await tools.list_emails(folder="INBOX", count=10)
        mock_imap4.assert_called_once()
        assert "Hello" in result

    @pytest.mark.asyncio
    async def test_list_emails_ssl_true_uses_ssl(self, tools):
        """Test that encryption_method='implicit' (default) connects via imaplib.IMAP4_SSL."""
        tools.valves.encryption_method = EncryptionMode.implicit
        raw = _make_raw_email("sender@test.com", "recv@test.com", "Hello", "Body")
        emails = [(raw, "1")]
        mock_server = _make_mock_server(emails)
        with (
            patch("imaplib.IMAP4_SSL", return_value=mock_server) as mock_imap4_ssl,
            patch("imaplib.IMAP4"),
        ):
            result = await tools.list_emails(folder="INBOX", count=10)
        mock_imap4_ssl.assert_called_once()
        assert "Hello" in result
