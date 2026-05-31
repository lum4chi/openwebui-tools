"""Refactored error handler tests using parameterized data-driven approach."""

from dataclasses import dataclass, field
from unittest.mock import MagicMock, patch

import pytest

from imap_mailbox import Tools

from .conftest import _IMAP_EXCEPTION, _make_raw_email_with_attachment


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


# Group 1 (8): IMAP exceptions via _IMAP_EXCEPTION() on login
IMAP_EXCEPTION_TESTS: list[ErrorSpec] = [
    ErrorSpec("list_emails", {"folder": "INBOX", "count": 5}),
    ErrorSpec("list_inbox_emails", {"count": 5}, valve_overrides={"allow_list_inbox": True}),
    ErrorSpec("read_email", {"email_index": 1}),
    ErrorSpec("read_inbox_email", {"email_index": 1}, valve_overrides={"allow_list_inbox": True}),
    ErrorSpec("search_emails", {"query": "test", "count": 10}),
    ErrorSpec("delete_email", {"email_index": 1}, valve_overrides={"allow_delete_single": True}),
    ErrorSpec("delete_all_emails", {}, valve_overrides={"allow_delete_all": True}),
    ErrorSpec("archive_email", {"email_index": 1}, valve_overrides={"allow_archive": True}),
]


# Group 2 (15): Generic exceptions via patch imap_mailbox._IMAP_EXCEPTION=OSError
GENERIC_EXCEPTION_TESTS: list[ErrorSpec] = [
    ErrorSpec(
        "list_emails",
        {"folder": "INBOX", "count": 5},
        expected_error="Error connecting to IMAP server",
        exception_class=NotImplementedError,
        mock_login_exception_msg="Generic error",
    ),
    ErrorSpec(
        "list_inbox_emails",
        {"count": 5},
        expected_error="Error connecting to IMAP server",
        valve_overrides={"allow_list_inbox": True},
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
        "read_inbox_email",
        {"email_index": 1},
        expected_error="Error reading email",
        valve_overrides={"allow_list_inbox": True},
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
        valve_overrides={"allow_archive": True},
        exception_class=NotImplementedError,
        mock_login_exception_msg="Generic error",
    ),
    ErrorSpec(
        "list_archive_emails",
        {"count": 10},
        expected_error="Error connecting to IMAP server",
        valve_overrides={"allow_list_archive": True},
        exception_class=NotImplementedError,
        mock_login_exception_msg="Generic error",
    ),
    ErrorSpec(
        "read_archive_email",
        {"email_index": 1},
        expected_error="Error reading email",
        valve_overrides={"allow_list_archive": True},
        exception_class=NotImplementedError,
        mock_login_exception_msg="Generic error",
    ),
    ErrorSpec(
        "list_trash_emails",
        {"count": 10},
        expected_error="Error connecting to IMAP server",
        valve_overrides={"allow_list_trash": True},
        exception_class=NotImplementedError,
        mock_login_exception_msg="Generic error",
    ),
    ErrorSpec(
        "read_trash_email",
        {"email_index": 1},
        expected_error="Error reading email",
        valve_overrides={"allow_list_trash": True},
        exception_class=NotImplementedError,
        mock_login_exception_msg="Generic error",
    ),
    ErrorSpec(
        "list_sent_emails",
        {"count": 10},
        expected_error="Error connecting to IMAP server",
        valve_overrides={"allow_list_sent": True},
        exception_class=NotImplementedError,
        mock_login_exception_msg="Generic error",
    ),
    ErrorSpec(
        "read_sent_email",
        {"email_index": 1},
        expected_error="Error reading email",
        valve_overrides={"allow_list_sent": True},
        exception_class=NotImplementedError,
        mock_login_exception_msg="Generic error",
    ),
    ErrorSpec(
        "list_draft_emails",
        {"count": 10},
        expected_error="Error connecting to IMAP server",
        valve_overrides={"allow_list_drafts": True},
        exception_class=NotImplementedError,
        mock_login_exception_msg="Generic error",
    ),
]


# Group 3 (7): Missing server
SERVER_NOT_CONFIGURED_TESTS: list[ErrorSpec] = [
    ErrorSpec("list_emails", {"folder": "INBOX", "count": 5}),
    ErrorSpec("list_inbox_emails", {"count": 5}, valve_overrides={"allow_list_inbox": True}),
    ErrorSpec("read_email", {"email_index": 1}),
    ErrorSpec("search_emails", {"query": "test", "count": 10}),
    ErrorSpec("delete_email", {"email_index": 1}, valve_overrides={"allow_delete_single": True}),
    ErrorSpec("delete_all_emails", {}, valve_overrides={"allow_delete_all": True}),
    ErrorSpec("archive_email", {"email_index": 1}, valve_overrides={"allow_archive": True}),
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
# Special-case tests (different mock patterns — not data-driven)
# ══════════════════════════════════════════════════════════════════════════════


class TestGenericExceptionEmailCount:
    """Test generic exception in get_email_count (lines 835-836)."""

    @pytest.mark.asyncio
    async def test_get_email_count_generic_exception(self, tools):
        """Test get_email_count catches generic Exception."""
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
