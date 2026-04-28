"""
title: POP3 Mailbox Manager
author: lum4chi
author_url: https://github.com/lum4chi/openwebui-tools
description: Manage a generic POP3 mailbox. Supports listing, reading, searching, and deleting emails.
requirements:
version: 1.1.0
licence: MIT
required_open_webui_version: 0.5.0
"""

import email.message
import poplib
from contextlib import suppress
from datetime import datetime, timedelta
from email.header import decode_header
from email.utils import parsedate_to_datetime
from typing import TYPE_CHECKING, Union

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from email.message import EmailMessage, Message
else:
    # At runtime, email.message_from_bytes returns EmailMessage
    # but type stubs for poplib use the older Message type
    EmailMessage = email.message.EmailMessage
    Message = email.message.Message


class Tools:
    def __init__(self):
        self.valves = self.Valves()
        self.citation = False

    class Valves(BaseModel):
        pop3_server: str = Field(default="localhost", description="POP3 server hostname (e.g., mail.example.com)")
        pop3_port: int = Field(default=995, description="POP3 server port (995 for SSL, 110 for non-SSL)")
        username: str = Field(default="", description="POP3 mailbox username")
        password: str = Field(default="", description="POP3 mailbox password or app-specific password")
        use_ssl: bool = Field(default=True, description="Use SSL/TLS connection (set False for port 110)")
        timeout: int = Field(default=30, description="Connection timeout in seconds")

    def _decode_mime_header(self, header_value: str | None) -> str:
        """Decode a MIME header value that may be encoded."""
        if not header_value:
            return ""
        decoded_parts = decode_header(header_value)
        result = []
        for part, charset in decoded_parts:
            if isinstance(part, bytes):
                charset = charset or "utf-8"
                try:
                    result.append(part.decode(charset, errors="replace"))
                except (LookupError, UnicodeDecodeError):
                    result.append(part.decode("utf-8", errors="replace"))
            else:
                result.append(part)
        return " ".join(result)

    def _get_email_body(self, msg: Union["Message", "EmailMessage"], max_chars: int = 10000) -> str:
        """Extract the plain text body from an email message."""
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition", ""))
                if content_type == "text/plain" and "attachment" not in content_disposition:
                    charset = part.get_content_charset() or "utf-8"
                    try:
                        payload = part.get_payload(decode=True)
                        if isinstance(payload, bytes):
                            body = payload.decode(charset, errors="replace")
                            break
                    except (LookupError, UnicodeDecodeError, AttributeError):
                        continue
        else:
            charset = msg.get_content_charset() or "utf-8"
            try:
                payload = msg.get_payload(decode=True)
                if isinstance(payload, bytes):
                    body = payload.decode(charset, errors="replace")
            except (LookupError, UnicodeDecodeError, AttributeError):
                pass
        if len(body) > max_chars:
            body = body[:max_chars] + "\n\n... [truncated]"
        return body.strip()

    def _parse_email(self, raw_msg: bytes) -> dict:
        """Parse a raw email message into a structured dict."""
        msg = email.message_from_bytes(raw_msg)

        date_str = msg.get("Date", "")
        date_parsed = None
        if date_str:
            with suppress(ValueError, TypeError):
                date_parsed = parsedate_to_datetime(date_str)

        from_addr = self._decode_mime_header(msg.get("From", ""))
        to_addr = self._decode_mime_header(msg.get("To", ""))
        subject = self._decode_mime_header(msg.get("Subject", "(No Subject)"))

        body = self._get_email_body(msg)

        has_attachments = False
        attachment_count = 0
        if msg.is_multipart():
            for part in msg.walk():
                disposition = str(part.get("Content-Disposition", ""))
                if "attachment" in disposition:
                    has_attachments = True
                    attachment_count += 1

        return {
            "date": date_parsed.isoformat() if date_parsed else date_str,
            "from": from_addr,
            "to": to_addr,
            "subject": subject,
            "body": body,
            "has_attachments": has_attachments,
            "attachment_count": attachment_count,
            "message_id": msg.get("Message-ID", ""),
            "headers": {
                "Date": date_str,
                "From": from_addr,
                "To": to_addr,
                "Subject": subject,
                "Message-ID": msg.get("Message-ID", ""),
            },
        }

    def _connect(self):
        """Establish connection to POP3 server."""
        v = self.valves
        if v.use_ssl:
            server = poplib.POP3_SSL(v.pop3_server, v.pop3_port, timeout=v.timeout)
        else:
            server = poplib.POP3(v.pop3_server, v.pop3_port, timeout=v.timeout)
        server.user(v.username)
        server.pass_(v.password)
        return server

    async def list_emails(
        self, count: int = Field(default=10, description="Number of recent emails to list (default: 10)")
    ) -> str:
        """
        List emails in the POP3 mailbox. Returns a summary of the most recent emails.
        :param count: Number of recent emails to retrieve and display
        """
        if not self.valves.username or not self.valves.password:
            return "Error: POP3 credentials (username and password) are not configured in Valves."
        if not self.valves.pop3_server:
            return "Error: POP3 server is not configured in Valves."

        try:
            server = self._connect()
            msg_count, mailbox_size = server.stat()

            if msg_count == 0:
                server.quit()
                return "Mailbox is empty. No emails found."

            emails = []
            # Retrieve emails from most recent to oldest
            for i in range(msg_count, max(0, msg_count - count), -1):
                try:
                    status, raw_msg_bytes, _ = server.retr(i)
                    parsed = self._parse_email(b"\n".join(raw_msg_bytes) + b"\n")
                    emails.append(parsed)
                except Exception as e:
                    emails.append(
                        {
                            "date": "",
                            "from": "",
                            "to": "",
                            "subject": f"Error reading message {i}: {str(e)}",
                            "body": "",
                            "has_attachments": False,
                            "attachment_count": 0,
                            "message_id": "",
                            "headers": {},
                        }
                    )

            server.quit()

            result_lines = [f"Mailbox: {msg_count} total message(s) ({mailbox_size} bytes)\n"]
            for _idx, email_data in enumerate(emails):
                attachment_info = ""
                if email_data["has_attachments"]:
                    attachment_info = f" [{email_data['attachment_count']} attachment(s)]"
                body_preview = email_data["body"][:200] + "..." if len(email_data["body"]) > 200 else email_data["body"]
                result_lines.append(
                    f"---\n"
                    f"  From:    {email_data['from']}\n"
                    f"  Subject: {email_data['subject']}{attachment_info}\n"
                    f"  Date:    {email_data['date']}\n"
                    f"  Body:    {body_preview}"
                )

            return "\n".join(result_lines)

        except poplib.error_proto as e:
            return f"POP3 Error: {str(e)}. Check your credentials and server settings."
        except Exception as e:
            return f"Error connecting to POP3 server '{self.valves.pop3_server}': {str(e)}"

    async def read_email(
        self, email_index: int = Field(description="Index of the email to read (1-based, 1 = most recent)")
    ) -> str:
        """
        Read a specific email by its index in the mailbox.
        :param email_index: 1-based index (1 = most recent email)
        """
        if not self.valves.username or not self.valves.password:
            return "Error: POP3 credentials (username and password) are not configured in Valves."
        if not self.valves.pop3_server:
            return "Error: POP3 server is not configured in Valves."

        try:
            server = self._connect()
            msg_count, _ = server.stat()

            if email_index < 1 or email_index > msg_count:
                server.quit()
                return f"Error: Email index {email_index} is out of range. Mailbox has {msg_count} message(s)."

            status, raw_msg_bytes, _ = server.retr(email_index)
            parsed = self._parse_email(b"\n".join(raw_msg_bytes) + b"\n")
            server.quit()

            attachment_info = ""
            if parsed["has_attachments"]:
                attachment_info = f"\n  Attachments: {parsed['attachment_count']} file(s) attached"

            result = (
                f"=== Email {email_index}/{msg_count} ===\n"
                f"  From:      {parsed['from']}\n"
                f"  To:        {parsed['to']}\n"
                f"  Subject:   {parsed['subject']}\n"
                f"  Date:      {parsed['date']}\n"
                f"  Message-ID:{parsed['message_id']}\n"
                f"{attachment_info}\n"
                f"  --- Body ---\n"
                f"  {parsed['body']}"
            )
            return result

        except poplib.error_proto as e:
            return f"POP3 Error: {str(e)}"
        except Exception as e:
            return f"Error reading email: {str(e)}"

    async def search_emails(
        self,
        query: str = Field(
            description="Search query to filter emails. Can specify 'from:<sender>', 'subject:<text>', 'before:<YYYY-MM-DD>', 'after:<YYYY-MM-DD>'"
        ),
        count: int = Field(default=10, description="Maximum number of results to return (default: 10)"),
    ) -> str:
        """
        Search emails in the mailbox by sender, subject, or date range.
        :param query: Search criteria (e.g., 'from:alice@example.com', 'subject:invoice', 'after:2025-01-01')
        :param count: Maximum number of results
        """
        if not self.valves.username or not self.valves.password:
            return "Error: POP3 credentials (username and password) are not configured in Valves."
        if not self.valves.pop3_server:
            return "Error: POP3 server is not configured in Valves."

        # Parse search criteria
        search_from = None
        search_subject = None
        search_after = None
        search_before = None

        parts = query.strip().split()
        for part in parts:
            if part.lower().startswith("from:"):
                search_from = part[5:].lower()
            elif part.lower().startswith("subject:"):
                search_subject = part[8:].lower()
            elif part.lower().startswith("after:"):
                with suppress(ValueError):
                    search_after = datetime.strptime(part[6:], "%Y-%m-%d")
            elif part.lower().startswith("before:"):
                with suppress(ValueError):
                    search_before = datetime.strptime(part[7:], "%Y-%m-%d") + timedelta(days=1)
            else:
                # Fallback: search in subject and body
                search_subject = part.lower()

        try:
            server = self._connect()
            msg_count, _ = server.stat()

            matches = []
            for i in range(msg_count, 0, -1):
                if len(matches) >= count:
                    break
                try:
                    status, raw_msg_bytes, _ = server.retr(i)
                    parsed = self._parse_email(b"\n".join(raw_msg_bytes) + b"\n")

                    # Apply filters
                    if search_from and search_from not in parsed["from"].lower():
                        continue
                    if (
                        search_subject
                        and search_subject not in parsed["subject"].lower()
                        and search_subject not in parsed["body"].lower()
                    ):
                        continue
                    if search_after or search_before:
                        try:
                            parsed_date = parsed["date"]
                            if parsed_date:
                                dt = parsedate_to_datetime(parsed_date)
                                if search_after and dt.date() < search_after.date():
                                    continue
                                if search_before and dt.date() >= search_before.date():
                                    continue
                        except (ValueError, TypeError):
                            continue

                    matches.append(parsed)
                except Exception:
                    continue

            server.quit()

            if not matches:
                return f"No emails found matching criteria: {query}"

            result_lines = [f"Found {len(matches)} email(s) matching: {query}\n"]
            for _idx, email_data in enumerate(matches):
                attachment_info = ""
                if email_data["has_attachments"]:
                    attachment_info = f" [{email_data['attachment_count']} attachment(s)]"
                body_preview = email_data["body"][:200] + "..." if len(email_data["body"]) > 200 else email_data["body"]
                result_lines.append(
                    f"---\n"
                    f"  From:    {email_data['from']}\n"
                    f"  Subject: {email_data['subject']}{attachment_info}\n"
                    f"  Date:    {email_data['date']}\n"
                    f"  Body:    {body_preview}"
                )

            return "\n".join(result_lines)

        except poplib.error_proto as e:
            return f"POP3 Error: {str(e)}"
        except Exception as e:
            return f"Error searching emails: {str(e)}"

    async def get_email_count(self) -> str:
        """
        Get the total number of emails in the mailbox.
        """
        if not self.valves.username or not self.valves.password:
            return "Error: POP3 credentials (username and password) are not configured in Valves."
        if not self.valves.pop3_server:
            return "Error: POP3 server is not configured in Valves."

        try:
            server = self._connect()
            msg_count, mailbox_size = server.stat()
            server.quit()
            return f"Mailbox contains {msg_count} message(s) ({mailbox_size} bytes total)."
        except poplib.error_proto as e:
            return f"POP3 Error: {str(e)}"
        except Exception as e:
            return f"Error checking mailbox: {str(e)}"

    async def delete_email(
        self, email_index: int = Field(description="Index of the email to delete (1-based, 1 = most recent)")
    ) -> str:
        """
        Delete a specific email from the mailbox.
        :param email_index: 1-based index (1 = most recent email)
        """
        if not self.valves.username or not self.valves.password:
            return "Error: POP3 credentials (username and password) are not configured in Valves."
        if not self.valves.pop3_server:
            return "Error: POP3 server is not configured in Valves."

        try:
            server = self._connect()
            msg_count, _ = server.stat()

            if email_index < 1 or email_index > msg_count:
                server.quit()
                return f"Error: Email index {email_index} is out of range. Mailbox has {msg_count} message(s)."

            server.dele(email_index)
            server.quit()
            return f"Email {email_index} has been deleted successfully."

        except poplib.error_proto as e:
            return f"POP3 Error: {str(e)}"
        except Exception as e:
            return f"Error deleting email: {str(e)}"

    async def delete_all_emails(
        self,
    ) -> str:
        """
        Delete all emails from the mailbox.
        """
        if not self.valves.username or not self.valves.password:
            return "Error: POP3 credentials (username and password) are not configured in Valves."
        if not self.valves.pop3_server:
            return "Error: POP3 server is not configured in Valves."

        try:
            server = self._connect()
            msg_count, _ = server.stat()

            if msg_count == 0:
                server.quit()
                return "Mailbox is already empty. No emails to delete."

            for i in range(1, msg_count + 1):
                server.dele(i)

            server.quit()
            return f"All {msg_count} email(s) have been deleted successfully."

        except poplib.error_proto as e:
            return f"POP3 Error: {str(e)}"
        except Exception as e:
            return f"Error deleting emails: {str(e)}"
