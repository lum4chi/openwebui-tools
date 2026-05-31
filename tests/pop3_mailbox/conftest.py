"""Shared fixtures and POP3-specific helpers for POP3 mailbox tests."""

from unittest.mock import MagicMock

import pytest

from .. import test_helpers

# Re-export shared helpers
_make_raw_email_with_attachment = test_helpers._make_raw_email_with_attachment
_make_tools_pop3 = test_helpers._make_tools_pop3


# POP3-specific: _make_raw_email without Message-ID header
def _make_raw_email(from_addr: str, to_addr: str, subject: str, body: str) -> bytes:  # type: ignore[no-untyped-def]
    """Create a raw email bytes object for mocking (no Message-ID, matching original POP3 behavior)."""
    return test_helpers._make_raw_email(from_addr, to_addr, subject, body, include_message_id=False)


from pop3_mailbox import EncryptionMode, Tools


@pytest.fixture
def tools():
    """Provide a configured Tools instance for POP3 tests."""
    t = Tools()
    t.valves.pop3_server = "mail.example.com"
    t.valves.pop3_port = 995
    t.valves.username = "testuser"
    t.valves.password = "testpass"
    t.valves.encryption_method = EncryptionMode.implicit
    t.valves.timeout = 5
    return t


def _make_mock_server(msg_count: int, emails: list) -> MagicMock:
    """Create a mock POP3 server that returns the given emails.

    POP3 spec: index 1 = oldest, index N = newest.
    The tool iterates from msg_count down to 1 (newest to oldest).
    emails[0] = oldest, emails[-1] = newest.

    Returns each email line as a separate list element, matching real
    POP3 server behaviour (poplib.retr returns a list of lines).
    """
    mock_server = MagicMock()
    mock_server.stat.return_value = (msg_count, msg_count * 1000)

    def mock_retr(index):
        if 1 <= index <= msg_count:
            email_idx = index - 1
            if 0 <= email_idx < len(emails):
                lines = emails[email_idx].split(b"\r\n")
                return ("220 OK", lines, len(emails[email_idx]))
        return ("500 Error", [], 0)

    mock_server.retr.side_effect = mock_retr
    mock_server.quit.return_value = None
    return mock_server


# Aliases for backward compatibility
_make_mock_pop3_server = _make_mock_server
_mock_pop3_server = _make_mock_server
_mock_pop3_ssl_server = _make_mock_server
