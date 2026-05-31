"""Auto-generated test module."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


from unittest.mock import MagicMock, patch

from pop3_mailbox import EncryptionMode, Tools


class TestPOP3NonSSLExceptionPaths:
    """Test non-SSL connection exception paths for various operations."""

    @pytest.mark.asyncio
    async def test_read_email_non_ssl_connection_error(self):
        """Test read_email with non-SSL connection fails gracefully."""
        t = Tools()
        t.valves.username = "user"
        t.valves.password = "pass"
        t.valves.pop3_server = "pop3.example.com"
        t.valves.pop3_port = 110
        t.valves.encryption_method = EncryptionMode.starttls

        mock_server = MagicMock()
        mock_server.stat.side_effect = RuntimeError("connection refused")
        mock_server.quit.return_value = None

        with patch("poplib.POP3", return_value=mock_server):
            result = await t.read_email(email_index=1)
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_get_email_count_non_ssl_connection_error(self):
        """Test get_email_count with non-SSL connection fails gracefully."""
        t = Tools()
        t.valves.username = "user"
        t.valves.password = "pass"
        t.valves.pop3_server = "pop3.example.com"
        t.valves.pop3_port = 110
        t.valves.encryption_method = EncryptionMode.starttls

        mock_server = MagicMock()
        mock_server.stat.side_effect = RuntimeError("connection refused")
        mock_server.quit.return_value = None

        with patch("poplib.POP3", return_value=mock_server):
            result = await t.get_email_count()
        assert "Error" in result

