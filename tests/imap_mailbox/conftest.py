"""Shared fixtures and helpers for IMAP mailbox tests."""

import email as _email_module
import imaplib as _imaplib
import os
import sys
from collections.abc import Callable

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from email.mime.text import MIMEText

from imap_mailbox import EncryptionMode, Tools


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

_IMAP_EXCEPTION = getattr(_imaplib, "IMAP4Exception", Exception)


def _make_raw_email(from_addr: str, to_addr: str, subject: str, body: str) -> bytes:
    """Create a raw email bytes object for mocking."""
    msg = MIMEText(body, "plain")
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg["Date"] = "Mon, 21 Apr 2025 10:00:00 +0000"
    msg["Message-ID"] = f"<{subject.replace(' ', '')}@test.com>"
    return msg.as_bytes()


def _make_raw_email_with_attachment(from_addr: str, to_addr: str, subject: str, body: str) -> bytes:
    """Create a multipart email with one attachment for mocking."""
    from email.mime.base import MIMEBase
    from email.mime.multipart import MIMEMultipart

    msg = MIMEMultipart()
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg["Date"] = "Mon, 21 Apr 2025 10:00:00 +0000"
    msg["Message-ID"] = f"<{subject.replace(' ', '')}@test.com>"
    msg.attach(MIMEText(body, "plain"))
    part = MIMEBase("application", "octet-stream")
    part.set_payload(b"fake-attachment-content")
    part.add_header("Content-Disposition", "attachment", filename="document.pdf")
    msg.attach(part)
    return msg.as_bytes()


def _make_mock_email_data(raw_email: bytes, uid: str = "1") -> list:
    """Wrap raw email bytes in IMAP RFC822 fetch response format."""
    prefix = str(uid).encode() + b" (RFC822 {}]"
    return [prefix, raw_email]


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


def _make_tools_imap(override: dict | None = None) -> Tools:
    """Create a configured Tools instance for IMAP tests."""
    t = Tools()
    t.valves.imap_server = "mail.example.com"
    t.valves.imap_port = 993
    t.valves.username = "testuser"
    t.valves.password = "testpass"
    t.valves.encryption_method = EncryptionMode.implicit
    t.valves.timeout = 5
    t.valves.inbox_folder = "INBOX"
    if override:
        for k, v in override.items():
            setattr(t.valves, k, v)
    return t
