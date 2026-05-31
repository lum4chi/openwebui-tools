"""Auto-generated test module."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


from unittest.mock import patch

from pop3_mailbox import EncryptionMode, Tools

from .conftest import _make_mock_server, _make_raw_email


class TestPOP3NonSSLConnection:
    """Test non-SSL connection mode for POP3."""

    @pytest.mark.asyncio
    async def test_list_emails_non_ssl(self):
        """Test that encryption_method='starttls' connects via POP3 with STARTTLS upgrade."""
        t = Tools()
        t.valves.pop3_server = "mail.test.com"
        t.valves.pop3_port = 110
        t.valves.username = "user"
        t.valves.password = "pass"
        t.valves.encryption_method = EncryptionMode.starttls
        raw = _make_raw_email("a@b.com", "c@d.com", "Test", "Body")
        mock_server = _make_mock_server(1, [raw])
        with patch("poplib.POP3", return_value=mock_server):
            result = await t.list_emails(count=5)
        assert "Test" in result
        assert "1 total" in result

    @pytest.mark.asyncio
    async def test_list_emails_ssl_default(self):
        """Test that encryption_method='implicit' (default) uses POP3_SSL."""
        t = Tools()
        t.valves.pop3_server = "mail.test.com"
        t.valves.username = "user"
        t.valves.password = "pass"
        mock_server = _make_mock_server(0, [])
        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await t.list_emails(count=5)
        assert "empty" in result.lower() or "No emails" in result
        assert "poplib.POP3" not in result

