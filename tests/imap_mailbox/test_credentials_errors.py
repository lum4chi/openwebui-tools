"""Auto-generated test module."""

from unittest.mock import MagicMock, patch

import pytest

from imap_mailbox import Tools


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


class TestIMAPReadInboxEmailNoCredentials:
    """Test read_email with inbox folder returns error when credentials are missing."""

    @pytest.mark.asyncio
    async def test_read_inbox_email_no_credentials(self):
        """Test read_email with inbox folder returns error when credentials are missing."""
        t = Tools()
        result = await t.read_email(email_index=1, folder="INBOX")
        assert "Error" in result and "credentials" in result

    @pytest.mark.asyncio
    async def test_read_inbox_email_no_server(self):
        """Test read_email with inbox folder returns error when imap_server is not set."""
        t = Tools()
        t.valves.username = "testuser"
        t.valves.password = "testpass"
        result = await t.read_email(email_index=1, folder="INBOX")
        assert "Error" in result and "server" in result


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
            await t.delete_email(1)
