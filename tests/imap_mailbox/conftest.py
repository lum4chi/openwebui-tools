"""Shared fixtures and IMAP-specific helpers for IMAP mailbox tests."""

import contextlib
import email as _email_module
from collections.abc import Callable

import pytest

from .. import test_helpers

# Re-export shared helpers
_make_raw_email = test_helpers._make_raw_email
_make_raw_email_with_attachment = test_helpers._make_raw_email_with_attachment
_make_mock_email_data = test_helpers._make_mock_email_data
_make_tools_imap = test_helpers._make_tools_imap
_IMAP_EXCEPTION = test_helpers._IMAP_EXCEPTION

from imap_mailbox import EncryptionMode, Tools


@contextlib.contextmanager
def patch_imap_mailbox_attr(attr: str, new_value):
    """Temporarily replace an imap_mailbox module-level attribute."""
    import imap_mailbox

    orig = getattr(imap_mailbox, attr)
    setattr(imap_mailbox, attr, new_value)
    try:
        yield
    finally:
        setattr(imap_mailbox, attr, orig)


class SieveMockBuilder:
    """Configurable mock builder for ManageSieve client."""

    @staticmethod
    def make(
        active: str | None = "filter1",
        scripts: list[str] | None = None,
        side_effects: dict[str, Exception] | None = None,
        extra_returns: dict[str, str | tuple] | None = None,
    ):
        from unittest.mock import MagicMock

        _scripts = scripts if scripts is not None else ["filter1", "filter2", "spam_block"]
        client = MagicMock()
        client.connect.return_value = True
        client.listscripts.return_value = (active if active else None, _scripts)
        client.getscript.return_value = (
            'require "fileinto";\nif header :contains "Subject" "invoice" {\n  fileinto "Invoices";\n}'
        )
        if extra_returns:
            for method_name, ret_val in extra_returns.items():
                getattr(client, method_name).return_value = ret_val
        if side_effects:
            for method_name, exc in side_effects.items():
                getattr(client, method_name).side_effect = exc
        client.return_value = client
        return client

    @staticmethod
    def empty() -> "SieveMockBuilder":
        """Mock with no scripts."""
        return SieveMockBuilder.make(active=None, scripts=[])

    @staticmethod
    def factory_mock(active: str | None = "filter1", scripts: list[str] | None = None):
        """Create a MagicMock return value that wraps a SieveMockBuilder-created client.

        Used where imap_mailbox._try_sievelib_client needs to be patched with a callable
        that returns a configured client (as in test_sieve.py's try/finally tests).
        """
        from unittest.mock import MagicMock

        return MagicMock(return_value=SieveMockBuilder.make(active=active, scripts=scripts))


@pytest.fixture
def tools():
    """Provide a configured Tools instance for IMAP tests."""
    t = Tools()
    t.valves.imap_server = "mail.example.com"
    t.valves.imap_port = 993
    t.valves.username = "testuser"
    t.valves.password = "testpass"
    t.valves.encryption_method = EncryptionMode.implicit
    t.valves.timeout = 5
    t.valves.inbox_folder = "INBOX"
    return t


@pytest.fixture
def sieve_tools():
    """Provide a configured Tools instance for Sieve tests."""
    t = Tools()
    t.valves.imap_server = "sieve.example.com"
    t.valves.username = "testuser"
    t.valves.password = "testpass"
    t.valves.manage_sieve_server = ""
    t.valves.manage_sieve_port = 4190
    t.valves.manage_sieve_encryption = EncryptionMode.starttls
    t.valves.manage_sieve_timeout = 30
    return t


@pytest.fixture
def sieve_tools_implicit(sieve_tools):
    """Sieve tools with implicit TLS."""
    sieve_tools.valves.manage_sieve_encryption = EncryptionMode.implicit
    return sieve_tools


def _make_mock_server(emails: list[tuple], uid_prefix: str = "", override_uid: Callable | None = None):
    """Create a mock IMAP server that returns the given emails."""
    from unittest.mock import MagicMock

    mock_server = MagicMock()

    def uid_side_effect(cmd, criteria=None, *args, **kwargs):
        """Handle conn.uid() calls."""
        if override_uid is not None:
            return override_uid(cmd, criteria, *args, **kwargs)
        if cmd == "search":
            search_criteria = args[0] if args else criteria
            if search_criteria is None or "ALL" in search_criteria.upper():
                matching_uids = [uid for _, uid in emails]
                return ("OK", [" ".join(matching_uids).encode()])
            from_val = None
            subject_val = None
            for part in search_criteria.split():
                lo = part.lower()
                if lo.startswith("from") and not lo.startswith("since"):
                    if '"' in part:
                        from_val = part.split('"')[1]
                    else:
                        pl = search_criteria.split()
                        idx = pl.index(part) + 1
                        if idx < len(pl):
                            from_val = pl[idx].strip('"')
                elif lo.startswith("subject"):
                    if '"' in part:
                        subject_val = part.split('"')[1]
                    else:
                        pl = search_criteria.split()
                        idx = pl.index(part) + 1
                        if idx < len(pl):
                            subject_val = pl[idx].strip('"')
            matching_uids = []
            for raw_bytes, uid in emails:
                try:
                    msg = _email_module.message_from_bytes(raw_bytes)
                    fh = (msg.get("From", "") or "").lower()
                    sh = (msg.get("Subject", "") or "").lower()
                    if from_val and from_val.lower() not in fh:
                        continue
                    if subject_val and subject_val.lower() not in sh:
                        continue
                except Exception:
                    pass
                matching_uids.append(uid)
            return ("OK", [" ".join(matching_uids).encode()])
        elif cmd == "fetch":
            target_uid = criteria
            if isinstance(target_uid, (list, tuple)):
                target_uid = target_uid[0]
            for raw_bytes, uid in emails:
                if uid == target_uid:
                    return ("OK", [_make_mock_email_data(raw_bytes, uid)])
            return ("OK", [b""])
        elif cmd == "store":
            return ("OK", [b"FLAGS (\\Deleted)"])
        return ("OK", [b""])

    mock_server.login.return_value = ("OK", [b"Login successful"])
    mock_server.select.return_value = ("OK", [b"0 Messages"])
    mock_server.uid.side_effect = uid_side_effect
    mock_server.logout.return_value = ("OK", [b"Logout successful"])
    mock_server.expunge.return_value = ("OK", [b"EXPUNGE"])
    mock_server.close.return_value = None

    return mock_server
