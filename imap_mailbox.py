"""
title: IMAP Mailbox Manager
author: lum4chi
author_url: https://github.com/lum4chi/openwebui-tools
description: Manage a generic IMAP mailbox. Supports listing, reading, searching, and deleting emails via IMAP.
requirements:
version: 1.1.0
licence: MIT
required_open_webui_version: 0.5.0
"""

import email.message
import imaplib
from contextlib import suppress
from datetime import datetime, timedelta
from email.header import decode_header
from email.utils import parsedate_to_datetime
from typing import TYPE_CHECKING, Union

from pydantic import BaseModel, Field

# Compatibility: imaplib.IMAP4Exception may not exist in all Python versions
try:
    _IMAP_EXCEPTION = imaplib.IMAP4Exception  # pyright: ignore[reportAttributeAccessIssue]
except AttributeError:
    _IMAP_EXCEPTION = Exception


if TYPE_CHECKING:
    from email.message import EmailMessage, Message
else:
    EmailMessage = email.message.EmailMessage
    Message = email.message.Message


class Tools:
    def __init__(self):
        self.valves = self.Valves()
        self.citation = False

    class Valves(BaseModel):
        imap_server: str = Field(default="", description="IMAP server hostname (e.g., mail.example.com)")
        imap_port: int = Field(default=993, description="IMAP server port (993 for SSL, 143 for non-SSL)")
        username: str = Field(default="", description="IMAP mailbox username")
        password: str = Field(default="", description="IMAP mailbox password or app-specific password")
        use_ssl: bool = Field(default=True, description="Use SSL/TLS connection (set False for port 143)")
        timeout: int = Field(default=30, description="Connection timeout in seconds")
        folder: str = Field(default="INBOX", description="IMAP folder to work with (default: INBOX)")
        allow_delete_single: bool = Field(
            default=False, description="Allow deleting individual emails (default: False for safety)"
        )
        allow_delete_all: bool = Field(
            default=False, description="Allow deleting all emails (default: False for safety)"
        )

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

    def _parse_email(self, raw_data: bytes) -> dict:
        """Parse raw email bytes into a structured dict."""
        msg = email.message_from_bytes(raw_data)

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

    def _connect(self) -> imaplib.IMAP4_SSL | imaplib.IMAP4:
        """Establish connection to IMAP server and select folder."""
        v = self.valves
        if v.use_ssl:
            conn = imaplib.IMAP4_SSL(v.imap_server, v.imap_port, timeout=v.timeout)
        else:
            conn = imaplib.IMAP4(v.imap_server, v.imap_port, timeout=v.timeout)
        conn.login(v.username, v.password)
        return conn

    def _refresh_uid_index(self, conn: imaplib.IMAP4 | imaplib.IMAP4_SSL) -> dict[str, int]:
        """Return a mapping from UID string -> sort position (1 = newest/highest UID).

        Uses UID numbers as a proxy for recency. UIDs may have gaps due to deletions,
        so we assign consecutive 1-based positions from highest UID downward.
        """
        _, uid_data = conn.uid("search", None, "ALL")  # type: ignore[arg-type]
        if uid_data[0] is None:
            return {}

        uid_string = uid_data[0].decode("utf-8").strip()
        if not uid_string:
            return {}

        uid_list = []
        for uid_str in uid_string.split():
            uid_bytes = uid_str
            if isinstance(uid_bytes, str):
                uid_bytes = uid_bytes.encode("utf-8")
            uid_list.append(uid_bytes.decode("utf-8"))

        # Sort by UID numerically (descending order = newest first for display)
        uid_list.sort(key=lambda u: int(u))
        uid_list.reverse()

        # Map: UID string -> 1-based index (1 = highest/newest UID)
        return {uid: idx + 1 for idx, uid in enumerate(uid_list)}

    async def list_emails(
        self, count: int = Field(default=10, description="Number of recent emails to list (default: 10)")
    ) -> str:
        """
        List emails in the IMAP mailbox. Returns a summary of the most recent emails.
        :param count: Number of recent emails to retrieve and display
        """
        if not self.valves.username or not self.valves.password:
            return "Error: IMAP credentials (username and password) are not configured in Valves."
        if not self.valves.imap_server:
            return "Error: IMAP server is not configured in Valves."

        try:
            conn = self._connect()
            conn.select(self.valves.folder, readonly=True)

            uid_map = self._refresh_uid_index(conn)

            if not uid_map:
                conn.close()
                return "Mailbox is empty. No emails found."

            # Get top N UIDs by index (1-based = newest first)
            reversed_map = {v: k for k, v in uid_map.items()}
            target_uids = []
            for idx in range(1, min(count + 1, len(reversed_map) + 1)):
                target_uids.append(reversed_map[idx])

            emails = []
            for uid in target_uids:
                try:
                    _, raw_data = conn.uid("fetch", uid, "(RFC822)")
                    raw_bytes = raw_data[0][1] if raw_data and len(raw_data) > 0 else b""
                    parsed = self._parse_email(raw_bytes)
                    parsed["uid"] = uid
                    emails.append(parsed)
                except Exception as e:
                    emails.append(
                        {
                            "date": "",
                            "from": "",
                            "to": "",
                            "subject": f"Error reading message {uid}: {str(e)}",
                            "body": "",
                            "has_attachments": False,
                            "attachment_count": 0,
                            "message_id": "",
                            "uid": uid,
                            "headers": {},
                        }
                    )

            conn.close()

            total_count = len(uid_map)

            result_lines = [f"Mailbox: {total_count} total message(s) in '{self.valves.folder}'\n"]
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
                    f"  UID:     {email_data.get('uid', '')}\n"
                    f"  Body:    {body_preview}"
                )

            return "\n".join(result_lines)

        except _IMAP_EXCEPTION as e:
            return f"IMAP Error: {str(e)}. Check your credentials and server settings."
        except Exception as e:
            return f"Error connecting to IMAP server '{self.valves.imap_server}': {str(e)}"

    async def read_email(
        self, email_index: int = Field(description="Index of the email to read (1-based, 1 = most recent by UID)")
    ) -> str:
        """
        Read a specific email by its index in the mailbox.
        :param email_index: 1-based index (1 = most recent email by UID)
        """
        if not self.valves.username or not self.valves.password:
            return "Error: IMAP credentials (username and password) are not configured in Valves."
        if not self.valves.imap_server:
            return "Error: IMAP server is not configured in Valves."

        try:
            conn = self._connect()
            conn.select(self.valves.folder, readonly=True)

            uid_map = self._refresh_uid_index(conn)

            if not uid_map:
                conn.close()
                return f"Error: Mailbox '{self.valves.folder}' is empty. No emails to read."

            # Get the UID for this index (uid_map = {uid: index} => build reversed)
            try:
                uid_map_rev: dict[int, str] = {}
                for uid_str, pos in uid_map.items():
                    uid_map_rev[pos] = uid_str
                uid = uid_map_rev[email_index]  # type: ignore[typeddict-item]
            except (KeyError, TypeError):
                conn.close()
                return f"Error: Email index {email_index} is out of range. Mailbox has {len(uid_map)} message(s)."

            _, raw_data = conn.uid("fetch", uid, "(RFC822)")  # type: ignore[arg-type]
            raw_bytes = raw_data[0][1] if raw_data and len(raw_data) > 0 else b""
            parsed = self._parse_email(raw_bytes)

            total_count = len(uid_map)
            conn.close()

            attachment_info = ""
            if parsed["has_attachments"]:
                attachment_info = f"\n  Attachments: {parsed['attachment_count']} file(s) attached"

            result = (
                f"=== Email [{uid}]/{total_count} in '{self.valves.folder}' ===\n"
                f"  From:      {parsed['from']}\n"
                f"  To:        {parsed['to']}\n"
                f"  Subject:   {parsed['subject']}\n"
                f"  Date:      {parsed['date']}\n"
                f"  UID:       {uid}\n"
                f"  Message-ID:{parsed['message_id']}\n"
                f"{attachment_info}\n"
                f"  --- Body ---\n"
                f"  {parsed['body']}"
            )
            return result

        except _IMAP_EXCEPTION as e:
            return f"IMAP Error: {str(e)}"
        except Exception as e:
            return f"Error reading email: {str(e)}"

    async def search_emails(
        self,
        query: str = Field(
            description="Search query to filter emails. Supports 'from:<sender>', 'subject:<text>', 'before:<YYYY-MM-DD>', 'after:<YYYY-MM-DD>'"
        ),
        count: int = Field(default=10, description="Maximum number of results to return (default: 10)"),
    ) -> str:
        """
        Search emails in the mailbox by sender, subject, or date range.
        :param query: Search criteria (e.g., 'from:alice@example.com', 'subject:invoice', 'after:2025-01-01')
        :param count: Maximum number of results
        """
        if not self.valves.username or not self.valves.password:
            return "Error: IMAP credentials (username and password) are not configured in Valves."
        if not self.valves.imap_server:
            return "Error: IMAP server is not configured in Valves."

        # Parse search criteria
        search_from: str | None = None
        search_subject: str | None = None
        search_after: datetime | None = None
        search_before: datetime | None = None
        search_text: str | None = None

        parts = query.strip().split()
        for part in parts:
            if part.lower().startswith("from:"):
                search_from = part[5:].strip('"')
            elif part.lower().startswith("subject:"):
                search_subject = part[8:].strip('"')
            elif part.lower().startswith("after:"):
                with suppress(ValueError):
                    search_after = datetime.strptime(part[6:], "%Y-%m-%d")
            elif part.lower().startswith("before:"):
                with suppress(ValueError):
                    search_before = datetime.strptime(part[7:], "%Y-%m-%d") + timedelta(days=1)
            else:
                search_text = part

        try:
            conn = self._connect()
            conn.select(self.valves.folder, readonly=True)

            # Build IMAP SEARCH criteria
            imap_criteria_parts = []

            if search_after:
                imap_criteria_parts.append(f"SINCE {search_after.strftime('%d-%b-%Y')}")
            if search_before and search_after is not None and search_before > search_after:
                imap_criteria_parts.append(f"BEFORE {search_before.strftime('%d-%b-%Y')}")
            if search_from:
                imap_criteria_parts.append(f'FROM "{search_from}"')
            if search_subject:
                imap_criteria_parts.append(f'SUBJECT "{search_subject}"')

            if imap_criteria_parts:
                criteria = " ".join(imap_criteria_parts)
                _, uid_data = conn.uid("search", None, criteria)  # pyright: ignore[reportArgumentType]
            else:
                _, uid_data = conn.uid("search", None, "ALL")  # pyright: ignore[reportArgumentType]

            if uid_data[0] is None:
                conn.close()
                return f"No emails found matching criteria: {query}"

            uid_string = uid_data[0].decode("utf-8").strip()
            if not uid_string:
                conn.close()
                return f"No emails found matching criteria: {query}"

            candidate_uids = uid_string.split()

            # If there's free-text search, do client-side filtering
            if search_text:
                filtered = []
                for uid in candidate_uids:
                    if len(filtered) >= count:
                        break
                    try:
                        _, raw_data = conn.uid("fetch", uid, "(RFC822)")
                        raw_bytes = raw_data[0][1] if raw_data and len(raw_data) > 0 else b""
                        parsed = self._parse_email(raw_bytes)
                        if (
                            search_text.lower() in parsed["subject"].lower()
                            or search_text.lower() in parsed["body"].lower()
                        ):
                            filtered.append(parsed)
                    except Exception:
                        continue
                matches = filtered
            else:
                # Fetch all candidate emails (limited by count)
                matches = []
                for uid in candidate_uids[:count]:
                    try:
                        _, raw_data = conn.uid("fetch", uid, "(RFC822)")
                        raw_bytes = raw_data[0][1] if raw_data and len(raw_data) > 0 else b""
                        parsed = self._parse_email(raw_bytes)
                        matches.append(parsed)
                    except Exception:
                        continue

            conn.close()

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

        except _IMAP_EXCEPTION as e:
            return f"IMAP Error: {str(e)}"
        except Exception as e:
            return f"Error searching emails: {str(e)}"

    async def get_email_count(self) -> str:
        """
        Get the total number of emails in the mailbox folder.
        """
        if not self.valves.username or not self.valves.password:
            return "Error: IMAP credentials (username and password) are not configured in Valves."
        if not self.valves.imap_server:
            return "Error: IMAP server is not configured in Valves."

        try:
            conn = self._connect()
            conn.select(self.valves.folder, readonly=True)

            uid_count = 0
            _, uid_data = conn.uid("search", None, "ALL")  # pyright: ignore[reportArgumentType]
            if uid_data[0]:
                uid_string = uid_data[0].decode("utf-8").strip()
                if uid_string:
                    uid_count = len(uid_string.split())

            conn.close()
            return f"Mailbox '{self.valves.folder}' contains {uid_count} message(s)."
        except _IMAP_EXCEPTION as e:
            return f"IMAP Error: {str(e)}"
        except Exception as e:
            return f"Error checking mailbox: {str(e)}"

    async def delete_email(
        self, email_index: int = Field(description="Index of the email to delete (1-based, 1 = most recent by UID)")
    ) -> str:
        """
        Delete a specific email from the mailbox.
        :param email_index: 1-based index (1 = most recent email by UID)
        """
        if not self.valves.allow_delete_single:
            return "Delete operations are disabled. Enable 'allow_delete_single' in Valves to use this feature."
        if not self.valves.username or not self.valves.password:
            return "Error: IMAP credentials (username and password) are not configured in Valves."
        if not self.valves.imap_server:
            return "Error: IMAP server is not configured in Valves."

        try:
            conn = self._connect()
            conn.select(self.valves.folder)

            uid_map = self._refresh_uid_index(conn)

            if not uid_map:
                conn.close()
                return f"Error: Mailbox '{self.valves.folder}' is empty. Nothing to delete."

            try:
                uid_map_rev: dict[int, str] = {}
                for uid_str, pos in uid_map.items():
                    uid_map_rev[pos] = uid_str
                uid = uid_map_rev[email_index]
            except (KeyError, TypeError):
                conn.close()
                return f"Error: Email index {email_index} is out of range. Mailbox has {len(uid_map)} message(s)."

            # Mark as deleted and expunge
            conn.uid("store", uid, "+FLAGS", "(\\Deleted)")  # pyright: ignore[reportArgumentType]
            conn.expunge()
            conn.close()
            return f"Email [{uid}] in '{self.valves.folder}' has been deleted successfully."

        except _IMAP_EXCEPTION as e:
            return f"IMAP Error: {str(e)}"
        except Exception as e:
            return f"Error deleting email: {str(e)}"

    async def delete_all_emails(
        self,
    ) -> str:
        """
        Delete all emails from the mailbox folder.
        """
        if not self.valves.allow_delete_all:
            return "Delete operations are disabled. Enable 'allow_delete_all' in Valves to use this feature."
        if not self.valves.username or not self.valves.password:
            return "Error: IMAP credentials (username and password) are not configured in Valves."
        if not self.valves.imap_server:
            return "Error: IMAP server is not configured in Valves."

        try:
            conn = self._connect()
            conn.select(self.valves.folder)

            uid_map = self._refresh_uid_index(conn)

            if not uid_map:
                conn.close()
                return "Mailbox is already empty. No emails to delete."

            uid_list = list(uid_map.keys())
            for uid in uid_list:
                conn.uid("store", uid, "+FLAGS", "(\\Deleted)")

            conn.expunge()
            conn.close()
            return f"All {len(uid_list)} email(s) in '{self.valves.folder}' have been deleted successfully."

        except _IMAP_EXCEPTION as e:
            return f"IMAP Error: {str(e)}"
        except Exception as e:
            return f"Error deleting emails: {str(e)}"
