"""Auto-generated test module."""

import pytest

from pop3_mailbox import Tools


class TestPOP3MissingGates:
    """Basic credential guards for access methods."""

    @pytest.mark.asyncio
    async def test_list_emails_disabled_by_default(self):
        """Test list_emails is disabled by default for non-IMAP."""
        t = Tools()
        result = await t.list_emails()
        assert result and "not" in result.lower()

    @pytest.mark.asyncio
    async def test_read_email_missing_credentials(self):
        """Test read_email when credentials are missing."""
        t = Tools()
        result = await t.read_email(email_index=1)
        assert "credentials" in result.lower()

    @pytest.mark.asyncio
    async def test_list_emails_missing_username(self):
        """Test list_emails when username is empty (line 171-172)."""
        t = Tools()
        t.valves.password = "pass"
        t.valves.pop3_server = "pop3.example.com"
        result = await t.list_emails(count=5)
        assert "credentials" in result.lower()

    @pytest.mark.asyncio
    async def test_list_emails_missing_server(self):
        """Test list_emails when pop3_server is empty (line 173-174)."""
        t = Tools()
        t.valves.username = "user"
        t.valves.password = "pass"
        t.valves.pop3_server = ""
        result = await t.list_emails(count=5)
        assert "server is not configured" in result

    @pytest.mark.asyncio
    async def test_read_email_missing_server(self):
        """Test read_email when pop3_server is empty (line 238-239)."""
        t = Tools()
        t.valves.username = "user"
        t.valves.password = "pass"
        t.valves.pop3_server = ""
        result = await t.read_email(email_index=1)
        assert "server is not configured" in result

    @pytest.mark.asyncio
    async def test_read_email_missing_username(self):
        """Test read_email when username is empty (line 236-237)."""
        t = Tools()
        t.valves.password = "pass"
        t.valves.pop3_server = "pop3.example.com"
        result = await t.read_email(email_index=1)
        assert "credentials" in result.lower()

    @pytest.mark.asyncio
    async def test_search_emails_missing_server(self):
        """Test search_emails when pop3_server is empty (line 289-290)."""
        t = Tools()
        t.valves.username = "user"
        t.valves.password = "pass"
        t.valves.pop3_server = ""
        result = await t.search_emails(query="test")
        assert "server is not configured" in result

    @pytest.mark.asyncio
    async def test_get_email_count_missing_server(self):
        """Test get_email_count when pop3_server is empty (line 383-384)."""
        t = Tools()
        t.valves.username = "user"
        t.valves.password = "pass"
        t.valves.pop3_server = ""
        result = await t.get_email_count()
        assert "server is not configured" in result

    @pytest.mark.asyncio
    async def test_delete_email_missing_server(self):
        """Test delete_email when pop3_server is empty (line 407-408)."""
        t = Tools()
        t.valves.username = "user"
        t.valves.password = "pass"
        t.valves.allow_delete_single = True
        t.valves.pop3_server = ""
        result = await t.delete_email(email_index=1)
        assert "server is not configured" in result

    @pytest.mark.asyncio
    async def test_delete_all_emails_missing_server(self):
        """Test delete_all_emails when pop3_server is empty (line 437-438)."""
        t = Tools()
        t.valves.username = "user"
        t.valves.password = "pass"
        t.valves.allow_delete_all = True
        t.valves.pop3_server = ""
        result = await t.delete_all_emails()
        assert "server is not configured" in result


class TestPOP3MissingGatesAdditional:
    """Additional credential guards for search and get_email_count."""

    @pytest.mark.asyncio
    async def test_search_missing_username(self):
        """Test search_emails when username is empty."""
        t = Tools()
        t.valves.password = "pass"
        t.valves.pop3_server = "pop3.example.com"
        result = await t.search_emails(query="test", count=10)
        assert "credentials" in result.lower()

    @pytest.mark.asyncio
    async def test_get_email_count_missing_credentials(self):
        """Test get_email_count when credentials are missing."""
        t = Tools()
        t.valves.username = "user"
        t.valves.password = ""
        t.valves.pop3_server = "pop3.example.com"
        result = await t.get_email_count()
        assert "credentials" in result.lower()
