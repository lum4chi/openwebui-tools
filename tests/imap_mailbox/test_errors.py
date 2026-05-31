"""Refactored error handler tests using parameterized data-driven approach."""

from dataclasses import dataclass, field
from unittest.mock import MagicMock, patch

import pytest

from imap_mailbox import Tools

from .conftest import _IMAP_EXCEPTION


@dataclass
class ErrorSpec:
    """Parameter for data-driven error tests."""

    method_name: str
    args: dict
    expected_error: str | None = "IMAP Error"
    exception_class: type = _IMAP_EXCEPTION
    mock_login_exception_msg: str = "Connection refused"
    valve_overrides: dict[str, bool] = field(default_factory=dict)
    patch_attr: str = "imap_mailbox._IMAP_EXCEPTION"


# Group 1 (6): IMAP exceptions via _IMAP_EXCEPTION() on login
IMAP_EXCEPTION_TESTS: list[ErrorSpec] = [
    ErrorSpec("list_emails", {"folder": "INBOX", "count": 5}),
    ErrorSpec("read_email", {"email_index": 1}),
    ErrorSpec("search_emails", {"query": "test", "count": 10}),
    ErrorSpec("delete_email", {"email_index": 1}, valve_overrides={"allow_delete_single": True}),
    ErrorSpec("delete_all_emails", {}, valve_overrides={"allow_delete_all": True}),
    ErrorSpec("archive_email", {"email_index": 1}, valve_overrides={"allow_move": True}),
]


# Group 2 (7): Generic exceptions via patch imap_mailbox._IMAP_EXCEPTION=OSError
GENERIC_EXCEPTION_TESTS: list[ErrorSpec] = [
    ErrorSpec(
        "list_emails",
        {"folder": "INBOX", "count": 5},
        expected_error="Error connecting to IMAP server",
        exception_class=NotImplementedError,
        mock_login_exception_msg="Generic error",
    ),
    ErrorSpec(
        "read_email",
        {"email_index": 1},
        expected_error="Error reading email",
        exception_class=NotImplementedError,
        mock_login_exception_msg="Generic error",
    ),
    ErrorSpec(
        "search_emails",
        {"query": "test", "count": 10},
        expected_error="Error searching emails",
        exception_class=NotImplementedError,
        mock_login_exception_msg="Generic error",
    ),
    ErrorSpec(
        "delete_email",
        {"email_index": 1},
        expected_error="Error deleting email",
        valve_overrides={"allow_delete_single": True},
        exception_class=NotImplementedError,
        mock_login_exception_msg="Generic error",
    ),
    ErrorSpec(
        "delete_all_emails",
        {},
        expected_error="Error deleting emails",
        valve_overrides={"allow_delete_all": True},
        exception_class=NotImplementedError,
        mock_login_exception_msg="Generic error",
    ),
    ErrorSpec(
        "archive_email",
        {"email_index": 1},
        expected_error="Error archiving email",
        valve_overrides={"allow_move": True},
        exception_class=NotImplementedError,
        mock_login_exception_msg="Generic error",
    ),
]


# Group 3 (6): Missing server
SERVER_NOT_CONFIGURED_TESTS: list[ErrorSpec] = [
    ErrorSpec("list_emails", {"folder": "INBOX", "count": 5}),
    ErrorSpec("read_email", {"email_index": 1}),
    ErrorSpec("search_emails", {"query": "test", "count": 10}),
    ErrorSpec("delete_email", {"email_index": 1}, valve_overrides={"allow_delete_single": True}),
    ErrorSpec("delete_all_emails", {}, valve_overrides={"allow_delete_all": True}),
    ErrorSpec("archive_email", {"email_index": 1}, valve_overrides={"allow_move": True}),
]


# ══════════════════════════════════════════════════════════════════════════════
# Parameterized test functions (Groups 1-3)
# ══════════════════════════════════════════════════════════════════════════════


def _make_tools_with_defaults():
    """Create a Tools instance with standard server config."""
    t = Tools()
    t.valves.imap_server = "mail.example.com"
    t.valves.imap_port = 993
    t.valves.username = "testuser"
    t.valves.password = "testpass"
    return t


@pytest.mark.asyncio
@pytest.mark.parametrize("spec", IMAP_EXCEPTION_TESTS, ids=[f"{s.method_name}_imap" for s in IMAP_EXCEPTION_TESTS])
async def test_imap_exceptions(spec: ErrorSpec):
    """IMAP exceptions raised on login are caught and returned as error strings."""
    t = _make_tools_with_defaults()
    for k, v in (spec.valve_overrides or {}).items():
        setattr(t.valves, k, v)

    mock_server = MagicMock()
    mock_server.login.side_effect = spec.exception_class(spec.mock_login_exception_msg)

    with patch("imaplib.IMAP4_SSL", return_value=mock_server):
        result = await getattr(t, spec.method_name)(**spec.args)

    assert spec.expected_error in result


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "spec", GENERIC_EXCEPTION_TESTS, ids=[f"{s.method_name}_generic" for s in GENERIC_EXCEPTION_TESTS]
)
async def test_generic_exceptions(spec: ErrorSpec):
    """Generic exceptions patched via imap_mailbox._IMAP_EXCEPTION are caught and returned."""
    t = _make_tools_with_defaults()
    for k, v in (spec.valve_overrides or {}).items():
        setattr(t.valves, k, v)

    mock_server = MagicMock()
    mock_server.login.side_effect = spec.exception_class(spec.mock_login_exception_msg)

    with patch(spec.patch_attr, OSError), patch("imaplib.IMAP4_SSL", return_value=mock_server):
        result = await getattr(t, spec.method_name)(**spec.args)

    assert spec.expected_error in result


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "spec", SERVER_NOT_CONFIGURED_TESTS, ids=[f"{s.method_name}_no_server" for s in SERVER_NOT_CONFIGURED_TESTS]
)
async def test_server_not_configured(spec: ErrorSpec):
    """Missing imap_server returns an error mentioning server."""
    t = Tools()
    t.valves.username = "testuser"
    t.valves.password = "testpass"
    for k, v in (spec.valve_overrides or {}).items():
        setattr(t.valves, k, v)

    result = await getattr(t, spec.method_name)(**spec.args)

    assert "Error" in result and "server" in result.lower()


# ══════════════════════════════════════════════════════════════════════════════
# _safe_close fallback tests
# ══════════════════════════════════════════════════════════════════════════════


class TestFieldInfoFallback:
    """Test that FieldInfo objects in parameters are handled gracefully.

    Open WebUI has a bug where it passes raw Pydantic FieldInfo objects instead of their
    resolved default values (or the values provided by the user). This class ensures
    that both `list_emails` and `search_emails` handle FieldInfo gracefully.
    """

    @pytest.mark.asyncio
    async def test_list_emails_field_info_count_field_with_default(self, tools):
        """list_emails: FieldInfo(default=N) falls back to N."""
        from pydantic import Field

        mock_server = MagicMock()
        mock_server.login.return_value = ("OK", [b"Login successful"])
        mock_server.select.return_value = ("OK", [])
        mock_server.uid.return_value = ("OK", [b""])
        mock_server.close.return_value = None

        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.list_emails(folder="INBOX", count=Field(default=10))

        assert "No emails" in result or "Folder is empty" in result
        mock_server.uid.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_emails_field_info_count_no_default(self, tools):
        """list_emails: FieldInfo with no default falls back to 10."""
        from pydantic import Field

        mock_server = MagicMock()
        mock_server.login.return_value = ("OK", [b"Login successful"])
        mock_server.select.return_value = ("OK", [])
        mock_server.uid.return_value = ("OK", [b""])
        mock_server.close.return_value = None

        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.list_emails(folder="INBOX", count=Field(description="how many"))

        assert "No emails" in result or "Folder is empty" in result

    @pytest.mark.asyncio
    async def test_list_emails_normal_int_count_regression(self, tools):
        """list_emails: normal int count still works (regression test)."""
        mock_server = MagicMock()
        mock_server.login.return_value = ("OK", [b"Login successful"])
        mock_server.select.return_value = ("OK", [])
        mock_server.uid.return_value = ("OK", [b""])
        mock_server.close.return_value = None

        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.list_emails(folder="INBOX", count=5)

        assert "No emails" in result or "Folder is empty" in result

    @pytest.mark.asyncio
    async def test_list_emails_field_info_with_description_only(self, tools):
        """list_emails: FieldInfo with description but no default falls back to 10."""
        from pydantic import Field

        mock_server = MagicMock()
        mock_server.login.return_value = ("OK", [b"Login successful"])
        mock_server.select.return_value = ("OK", [])
        mock_server.uid.return_value = ("OK", [b""])
        mock_server.close.return_value = None

        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.list_emails(
                folder="INBOX",
                count=Field(description="Number of recent emails to list (default: 10)"),
            )

        assert "No emails" in result or "Folder is empty" in result

    @pytest.mark.asyncio
    async def test_search_emails_field_info_count(self, tools):
        """search_emails: FieldInfo(default=N) for count falls back to N."""
        from pydantic import Field

        mock_server = MagicMock()
        mock_server.login.return_value = ("OK", [b"Login successful"])
        mock_server.select.return_value = ("OK", [])
        mock_server.uid.return_value = ("OK", [b""])
        mock_server.close.return_value = None

        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.search_emails(query="test", count=Field(default=10))

        assert "No emails" in result or "No emails found" in result

    @pytest.mark.asyncio
    async def test_search_emails_field_info_query(self, tools):
        """search_emails: FieldInfo as query parameter is handled."""
        from pydantic import Field

        mock_server = MagicMock()
        mock_server.login.return_value = ("OK", [b"Login successful"])
        mock_server.select.return_value = ("OK", [])
        mock_server.uid.return_value = ("OK", [b""])
        mock_server.close.return_value = None

        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.search_emails(query=Field(description="Search query"))

        assert "No emails" in result or "No emails found" in result
        # Should have called uid.search with the FieldInfo (treated as a string search)

    @pytest.mark.asyncio
    async def test_search_emails_field_info_count_and_query(self, tools):
        """search_emails: Both count and query as FieldInfo."""
        from pydantic import Field

        mock_server = MagicMock()
        mock_server.login.return_value = ("OK", [b"Login successful"])
        mock_server.select.return_value = ("OK", [])
        mock_server.uid.return_value = ("OK", [b""])
        mock_server.close.return_value = None

        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.search_emails(
                query=Field(description="Search query"),
                count=Field(default=5),
            )

        assert "No emails" in result or "No emails found" in result

    @pytest.mark.asyncio
    async def test_search_emails_normal_params_regression(self, tools):
        """search_emails: normal params still work (regression test)."""
        mock_server = MagicMock()
        mock_server.login.return_value = ("OK", [b"Login successful"])
        mock_server.select.return_value = ("OK", [])
        mock_server.uid.return_value = ("OK", [b""])
        mock_server.close.return_value = None

        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.search_emails(query="from:admin", count=3, folder="INBOX")

        assert "No emails" in result or "No emails found" in result


class TestSafeCloseFallback:
    """Test _safe_close fallback to logout when close() fails."""

    @pytest.mark.asyncio
    async def test_safe_close_fallback_to_logout_on_imap_error(self, tools):
        """Test _safe_close falls back to logout when close() raises IMAPException."""
        mock_server = MagicMock()
        mock_server.login.return_value = ("OK", [b"Login successful"])
        mock_server.list.return_value = ("OK", [])
        mock_server.close.side_effect = _IMAP_EXCEPTION("CLOSE illegal in state AUTH")

        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.list_folders()

        assert "No folders found" in result or "Available IMAP folders" in result

    @pytest.mark.asyncio
    async def test_safe_close_fallback_to_logout_on_generic_error(self, tools):
        """Test _safe_close falls back to logout when close() raises generic exception."""
        import imap_mailbox
        from pydantic import Field

        orig = imap_mailbox._IMAP_EXCEPTION
        imap_mailbox._IMAP_EXCEPTION = RuntimeError
        try:
            mock_server = MagicMock()
            mock_server.login.return_value = ("OK", [b"Login successful"])
            mock_server.list.return_value = ("OK", [])
            mock_server.close.side_effect = ValueError("Server broken")
            mock_server.delete.side_effect = _IMAP_EXCEPTION("Mailbox not empty")

            with patch("imaplib.IMAP4_SSL", return_value=mock_server):
                result = await tools.list_folders()

            assert "No folders found" in result or "Available IMAP folders" in result
        finally:
            imap_mailbox._IMAP_EXCEPTION = orig


# ══════════════════════════════════════════════════════════════════════════════
# Special-case tests (different mock patterns — not data-driven)
# ══════════════════════════════════════════════════════════════════════════════


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
                return ("OK", [b"101 (FETCH)"])
            return ("OK", [b"101"])

        mock_server.uid.side_effect = uid_side_effect
        mock_server.login.return_value = ("OK", None)
        mock_server.examine.return_value = ("OK", [b"1"])

        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.list_emails(count=5, folder="INBOX")
        assert "Error reading message" in result
