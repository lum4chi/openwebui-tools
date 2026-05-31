"""Auto-generated test module."""
import imaplib as _imaplib

import pytest

from imap_mailbox import Tools

_IMAP_EXCEPTION = getattr(_imaplib, "IMAP4Exception", Exception)





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

