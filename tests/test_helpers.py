"""Shared test helpers for IMAP and POP3 mailbox tests."""

import imaplib
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from imap_mailbox import EncryptionMode as ImapEncryptionMode
from imap_mailbox import Tools as ImapTools
from pop3_mailbox import EncryptionMode as Pop3EncryptionMode
from pop3_mailbox import Tools as Pop3Tools

_IMAP_EXCEPTION = getattr(imaplib, "IMAP4Exception", Exception)

# Re-export MIME classes for convenient use in test files
__all__ = [
    "_make_raw_email",
    "_make_raw_email_with_attachment",
    "_make_mock_email_data",
    "_make_tools_imap",
    "_make_tools_pop3",
    "MIMEText",
    "MIMEMultipart",
    "MIMEBase",
]


def _make_raw_email(from_addr: str, to_addr: str, subject: str, body: str, include_message_id: bool = True) -> bytes:
    """Create a raw email bytes object for mocking."""
    msg = MIMEText(body, "plain")
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg["Date"] = "Mon, 21 Apr 2025 10:00:00 +0000"
    if include_message_id:
        msg["Message-ID"] = f"<{subject.replace(' ', '')}@test.com>"
    return msg.as_bytes()


def _make_raw_email_with_attachment(from_addr: str, to_addr: str, subject: str, body: str) -> bytes:
    """Create a multipart email with one attachment for mocking."""
    msg = MIMEMultipart()
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg["Date"] = "Mon, 21 Apr 2025 10:00:00 +0000"
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


def _make_tools_imap(override: dict | None = None) -> ImapTools:
    """Create a configured IMAP Tools instance."""
    t = ImapTools()
    t.valves.imap_server = "mail.example.com"
    t.valves.imap_port = 993
    t.valves.username = "testuser"
    t.valves.password = "testpass"
    t.valves.encryption_method = ImapEncryptionMode.implicit
    t.valves.timeout = 5
    t.valves.inbox_folder = "INBOX"
    if override:
        for k, v in override.items():
            setattr(t.valves, k, v)
    return t


def _make_tools_pop3(override: dict | None = None) -> Pop3Tools:
    """Create a configured POP3 Tools instance."""
    t = Pop3Tools()
    t.valves.pop3_server = "mail.example.com"
    t.valves.pop3_port = 995
    t.valves.username = "testuser"
    t.valves.password = "testpass"
    t.valves.encryption_method = Pop3EncryptionMode.implicit
    t.valves.timeout = 5
    if override:
        for k, v in override.items():
            setattr(t.valves, k, v)
    return t
