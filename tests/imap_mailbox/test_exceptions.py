"""Auto-generated test module."""

from unittest.mock import MagicMock, patch

import pytest

from imap_mailbox import Tools

from .conftest import _IMAP_EXCEPTION, _make_mock_server


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
