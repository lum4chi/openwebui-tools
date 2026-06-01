"""
title: IMAP Mailbox Manager
author: lum4chi
author_url: https://github.com/lum4chi/openwebui-tools
description: Manage a generic IMAP mailbox. Supports listing, reading, searching, and deleting emails via IMAP. Also manages Sieve email filters via ManageSieve.
requirements: sievelib>=1.5.0
version: 3.1.0
licence: MIT
required_open_webui_version: 0.5.0
"""

import email.message
import imaplib
from contextlib import suppress
from datetime import datetime, timedelta
from email.header import decode_header
from email.utils import parsedate_to_datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field
from pydantic.fields import FieldInfo
from pydantic_core import PydanticUndefined
from sievelib.managesieve import Client


class EncryptionMode(StrEnum):
    """Encryption method for mail connections. Always encrypted — plaintext never allowed."""

    implicit = "implicit"  # TLS from the start (port 993/995)
    starttls = "starttls"  # Upgrade to TLS after connect (port 143/110/20000/4190)


# Compatibility: imaplib.IMAP4Exception may not exist in all Python versions
_IMAP_EXCEPTION = getattr(imaplib, "IMAP4Exception", Exception)


def _quote(s: str) -> str:
    """Quote an IMAP string literal per RFC 3501.

    IMAP requires strings containing special characters to be enclosed in
    double quotes with backslash and double-quote characters escaped.
    This matches :meth:`imaplib.IMAP4._quote`.

    Handles Pydantic FieldInfo objects (passed by Open WebUI) by resolving
    to the string value first.
    """
    if isinstance(s, FieldInfo):
        s = s.default
    if isinstance(s, str):
        s = s.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{s}"'
    return s


def _handle_sieve_list_result(
    result: tuple[str | None, list[str]] | None,
) -> tuple[str | None, list[str], str | None]:
    """Normalize the result of listscripts().

    handles the case where listscripts() returns None (server responded NO).
    Also fixes a sievelib issue: when a script name matches the ACTIVE marker,
    sievelib skips adding it to the scripts list. We include it back so
    getscript/setactive etc. work with the active script name.
    """
    if result is None:
        return (None, [], "Server responded that no scripts are available for this user.")
    try:
        active = result[0]
        scripts = result[1]
    except (TypeError, IndexError):
        # If result can't be unpacked (e.g. bare MagicMock in tests), pass through
        return (None, [], "Unexpected ManageSieve response format.")
    # Include active script in the list if it's a real list and not already there.
    # sievelib intentionally skips adding active scripts via CONTINUE;
    # this fixes that so getscript/setactive work with the active name.
    # Skip for MagicMock — let test mocks behave as they were configured.
    if active and isinstance(active, str) and isinstance(scripts, list) and active not in scripts:
        scripts.append(active)
    return active, scripts, None


class Tools:
    def __init__(self):
        self.valves = self.Valves()
        self.citation = False

    class Valves(BaseModel):
        # connection
        imap_server: str = Field(default="", description="IMAP server hostname (e.g., mail.example.com)")
        imap_port: int = Field(default=993, description="IMAP server port (993 for implicit TLS, 143 for STARTTLS)")
        username: str = Field(default="", description="IMAP mailbox username")
        password: str = Field(default="", description="IMAP mailbox password or app-specific password")
        encryption_method: EncryptionMode = Field(
            default=EncryptionMode.implicit,
            description="Encryption method: 'implicit' for TLS from start (port 993), 'starttls' for upgrade (port 143)",
        )
        timeout: int = Field(default=30, description="Connection timeout in seconds")

        # folders
        inbox_folder: str = Field(default="INBOX", description="Inbox folder name (default: 'INBOX')")
        archive_folder: str = Field(
            default="Archive", description="Archive folder name (e.g., 'Archive', '[Gmail]/All Mail')"
        )
        trash_folder: str = Field(
            default="Trash", description="Trash folder name; differs by provider (e.g., 'Deleted Items')"
        )
        sent_folder: str = Field(default="Sent", description="Sent folder name (e.g., 'Sent', 'Sent Items')")
        drafts_folder: str = Field(
            default="Drafts", description="Drafts folder name (e.g., 'Drafts', '[Gmail]/Drafts')"
        )

        # write permissions
        allow_delete_single: bool = Field(
            default=False, description="Allow deleting individual emails (default: False for safety)"
        )
        allow_delete_all: bool = Field(
            default=False, description="Allow deleting all emails (default: False for safety)"
        )
        allow_move: bool = Field(
            default=False, description="Allow moving emails between folders (default: False for safety)"
        )
        allow_create_folder: bool = Field(
            default=False,
            description="Allow creating new IMAP folders (default: False for safety)",
        )
        allow_delete_folder: bool = Field(
            default=False, description="Allow deleting IMAP folders (default: False for safety)"
        )

        # manage sieve
        manage_sieve_server: str = Field(
            default="", description="ManageSieve server hostname (default: same as imap_server)"
        )
        manage_sieve_port: int = Field(
            default=4190,
            description="ManageSieve server port. Always encrypted — use 'implicit' or 'starttls' for encryption mode.",
        )
        manage_sieve_encryption: EncryptionMode = Field(
            default=EncryptionMode.starttls,
            description="Encryption method for ManageSieve. 'starttls' for STARTTLS upgrade (mailbox.org), 'implicit' for TLS from start (e.g. some Dovecot setups)",
        )
        manage_sieve_timeout: int = Field(default=30, description="ManageSieve connection timeout in seconds")

        # write permissions for sieve
        allow_create_sieve: bool = Field(
            default=False, description="Allow creating or uploading Sieve scripts (default: False for safety)"
        )
        allow_update_sieve: bool = Field(
            default=False, description="Allow updating existing Sieve scripts (default: False for safety)"
        )
        allow_delete_sieve: bool = Field(
            default=False, description="Allow deleting Sieve scripts (default: False for safety)"
        )
        allow_activate_sieve: bool = Field(
            default=False, description="Allow activating/deactivating Sieve scripts (default: False for safety)"
        )

    def _manage_sieve_connect(self) -> str | object:
        """Establish connection to ManageSieve server.

        Returns a sievelib Client object on success, or an error string on failure.
        """
        if not self.valves.username or not self.valves.password:
            return "Error: IMAP credentials (username and password) are not configured in Valves. ManageSieve reuses IMAP credentials."
        if not self.valves.imap_server:
            return "Error: IMAP server is not configured in Valves. ManageSieve reuses IMAP host by default."

        server = self.valves.manage_sieve_server or self.valves.imap_server
        port = self.valves.manage_sieve_port

        try:
            client = Client(server, srvport=port)
            if self.valves.manage_sieve_encryption == EncryptionMode.implicit:
                # Implicit TLS — SSL from the start
                connected = client.connect(
                    self.valves.username,
                    self.valves.password,
                    ssl=True,
                    starttls=False,
                )
            else:
                # STARTTLS — upgrade after connecting
                connected = client.connect(
                    self.valves.username,
                    self.valves.password,
                    ssl=False,
                    starttls=True,
                )
            if connected is not True:
                return "ManageSieve Error: Connection or authentication failed. Check your server settings and credentials."
            return client
        except Exception as e:
            return f"ManageSieve Error: {str(e)}. Check your server settings and credentials."

    async def list_sieve_scripts(self) -> str:
        """List all available Sieve filters/scripts on the server.

        Note: Some providers (e.g. mailbox.org with Nextcloud/Open-Xchange)
        manage Sieve filters via their own API rather than standard
        ManageSieve. In those cases no scripts will be listed even though
        filters may be active on the server.
        """
        result = self._manage_sieve_connect()
        if isinstance(result, str):
            return result
        client = result
        try:
            active, scripts, err = _handle_sieve_list_result(client.listscripts())
            if scripts is None:
                client.logout()
                return "ManageSieve reports that no scripts are available for this account. This can happen if the ManageSieve service is disabled, the user lacks permission, or the server manages filters via another protocol (e.g. Open-Xchange, Nextcloud)."
            if not scripts:
                client.logout()
                return (
                    "No Sieve scripts found on the ManageSieve server.\n"
                    "Note: Some providers (e.g. mailbox.org with Nextcloud/Open-Xchange) manage filters via their own API. "
                    "The ACTIVITY/*.sieve files on disk are not always visible via ManageSieve."
                )
            active_label = " (active)" if active else " (none active)"
            result_lines = [f"Available Sieve scripts{active_label}:"]
            for name in sorted(scripts):
                marker = ">>>" if name == active else "   "
                result_lines.append(f"  {marker} {name}")
            client.logout()
            return "\n".join(result_lines)
        except Exception as e:
            with suppress(Exception):
                client.logout()
            return f"Error listing Sieve scripts: {str(e)}. Note: Some providers manage filters via non-standard ManageSieve endpoints."

    async def get_sieve_script(self, name: str = Field(description="Name of the Sieve script to retrieve")) -> str:
        """Get the content of a Sieve script."""
        result = self._manage_sieve_connect()
        if isinstance(result, str):
            return result
        client = result
        try:
            active, scripts, err = _handle_sieve_list_result(client.listscripts())
            if scripts is None:
                client.logout()
                return f"ManageSieve returned no scripts for this account. This usually means the server manages filters via Open-Xchange, Nextcloud, or another provider-specific API. The script '{name}' is likely not accessible via ManageSieve."
            if not scripts:
                client.logout()
                return f"No Sieve scripts found on the ManageSieve server. This is expected on providers that manage filters via their own API (e.g. mailbox.org with Nextcloud/Open-Xchange). The script '{name}' may still be active but not visible via ManageSieve."
            if name not in scripts:
                client.logout()
                return f"Error: Sieve script '{name}' not found. Available scripts: {', '.join(sorted(scripts))}"
            script_content = client.getscript(name)
            client.logout()
            return f"=== Sieve Script: {name} ===\n{script_content}"
        except Exception as e:
            with suppress(Exception):
                client.logout()
            return f"Error retrieving Sieve script: {str(e)}"

    async def create_sieve_script(
        self,
        name: str = Field(description="Name for the new Sieve script"),
        content: str = Field(description="Sieve script content (Sieve DSL format)"),
    ) -> str:
        """Create or upload a new Sieve script.

        Note: Some providers (e.g. mailbox.org with Nextcloud/Open-Xchange)
        do not support ManageSieve script upload. Scripts must be created
        via the provider's web interface.
        """
        if not self.valves.allow_create_sieve:
            return "Create script operations are disabled. Enable 'allow_create_sieve' in Valves to use this feature."
        result = self._manage_sieve_connect()
        if isinstance(result, str):
            return result
        client = result
        try:
            active, scripts, err = _handle_sieve_list_result(client.listscripts())
            if scripts is None:
                client.logout()
                return "ManageSieve returned no scripts for this account. Script creation via ManageSieve is likely not supported on this provider. Create scripts via the provider's web interface (e.g. Nextcloud Mail)."
            if name in scripts:
                client.logout()
                return f"Error: Sieve script '{name}' already exists. Use update_sieve_script to modify it."
            client.putscript(name, content)
            client.logout()
            return f"Sieve script '{name}' has been created successfully."
        except Exception as e:
            with suppress(Exception):
                client.logout()
            return f"Error creating Sieve script: {str(e)}"

    async def update_sieve_script(
        self,
        name: str = Field(description="Name of the existing Sieve script to update"),
        content: str = Field(description="Updated Sieve script content"),
    ) -> str:
        """Update an existing Sieve script."""
        if not self.valves.allow_update_sieve:
            return "Update script operations are disabled. Enable 'allow_update_sieve' in Valves to use this feature."
        result = self._manage_sieve_connect()
        if isinstance(result, str):
            return result
        client = result
        try:
            active, scripts, err = _handle_sieve_list_result(client.listscripts())
            if scripts is None:
                client.logout()
                return "ManageSieve returned no scripts for this account. Script updates via ManageSieve are likely not supported on this provider. Update scripts via the provider's web interface (e.g. Nextcloud Mail)."
            if not scripts:
                client.logout()
                return "No Sieve scripts found on the ManageSieve server. This is expected on providers that manage filters via their own API (e.g. mailbox.org with Nextcloud/Open-Xchange). Updates via ManageSieve will not affect the active filters."
            if name not in scripts:
                client.logout()
                return f"Error: Sieve script '{name}' not found. Available scripts: {', '.join(sorted(scripts))}"
            client.putscript(name, content)
            client.logout()
            return f"Sieve script '{name}' has been updated successfully."
        except Exception as e:
            with suppress(Exception):
                client.logout()
            return f"Error updating Sieve script: {str(e)}"

    async def delete_sieve_script(self, name: str = Field(description="Name of the Sieve script to delete")) -> str:
        """Delete a Sieve script from the server."""
        if not self.valves.allow_delete_sieve:
            return "Delete script operations are disabled. Enable 'allow_delete_sieve' in Valves to use this feature."
        result = self._manage_sieve_connect()
        if isinstance(result, str):
            return result
        client = result
        try:
            active, scripts, err = _handle_sieve_list_result(client.listscripts())
            if scripts is None:
                client.logout()
                return "ManageSieve returned no scripts for this account. Script deletion via ManageSieve is likely not supported on this provider. Delete scripts via the provider's web interface (e.g. Nextcloud Mail)."
            if not scripts:
                client.logout()
                return "No Sieve scripts found on the ManageSieve server. This is expected on providers that manage filters via their own API (e.g. mailbox.org with Nextcloud/Open-Xchange). Deletion via ManageSieve will not affect active filters."
            if name not in scripts:
                client.logout()
                return f"Error: Sieve script '{name}' not found. Available scripts: {', '.join(sorted(scripts))}"
            client.deletescript(name)
            if active == name:
                client.setactive(None)
            client.logout()
            return f"Sieve script '{name}' has been deleted successfully."
        except Exception as e:
            with suppress(Exception):
                client.logout()
            return f"Error deleting Sieve script: {str(e)}"

    async def set_active_sieve_script(
        self, name: str = Field(description="Name of the Sieve script to activate")
    ) -> str:
        """Activate a Sieve script (make it the active filter)."""
        if not self.valves.allow_activate_sieve:
            return (
                "Activate script operations are disabled. Enable 'allow_activate_sieve' in Valves to use this feature."
            )
        result = self._manage_sieve_connect()
        if isinstance(result, str):
            return result
        client = result
        try:
            active, scripts, err = _handle_sieve_list_result(client.listscripts())
            if scripts is None:
                client.logout()
                return "ManageSieve returned no scripts for this account. Activation via ManageSieve is likely not supported on this provider. Scripts are activated via the provider's own system (e.g. Nextcloud Mail)."
            if not scripts:
                client.logout()
                return "No Sieve scripts found on the ManageSieve server. This is expected on providers that manage filters via their own API. Script activation via ManageSieve is not possible."
            if name not in scripts:
                client.logout()
                return f"Error: Sieve script '{name}' not found. Available scripts: {', '.join(sorted(scripts))}"
            client.setactive(name)
            client.logout()
            return f"Sieve script '{name}' is now active."
        except Exception as e:
            with suppress(Exception):
                client.logout()
            return f"Error activating Sieve script: {str(e)}"

    async def deactivate_sieve_script(self) -> str:
        """Deactivate the currently active Sieve script (no scripts will filter mail)."""
        if not self.valves.allow_activate_sieve:
            return (
                "Activate script operations are disabled. Enable 'allow_activate_sieve' in Valves to use this feature."
            )
        result = self._manage_sieve_connect()
        if isinstance(result, str):
            return result
        client = result
        try:
            active, scripts, err = _handle_sieve_list_result(client.listscripts())
            if scripts is None:
                client.logout()
                return "ManageSieve returned no scripts for this account. Deactivation via ManageSieve is likely not supported on this provider. The provider's system manages which script is active."
            if not active:
                client.logout()
                return "No Sieve script is currently active."
            client.setactive(None)
            client.logout()
            return f"Sieve script '{active}' has been deactivated. No scripts are currently active."
        except Exception as e:
            with suppress(Exception):
                client.logout()
            return f"Error deactivating Sieve script: {str(e)}"

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

    def _get_email_body(self, msg: object, max_chars: int = 10000) -> str:
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
        """Establish connection to IMAP server."""
        v = self.valves
        if v.encryption_method == EncryptionMode.implicit:
            conn = imaplib.IMAP4_SSL(v.imap_server, v.imap_port, timeout=v.timeout)
        else:
            # starttls mode — always upgrade to TLS before login
            conn = imaplib.IMAP4(v.imap_server, v.imap_port, timeout=v.timeout)
            conn.starttls()
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

    def _resolve_fieldinfo(self, value: Any, fallback: Any) -> Any:
        """Resolve a value that may be a Pydantic FieldInfo (Open WebUI edge case).

        Open WebUI sometimes passes raw FieldInfo objects to tool methods. If that
        happens, extract the default value (or return fallback if the FieldInfo
        has no default). Normal values pass through unchanged.
        """
        if isinstance(value, (str, int, list)):
            return value
        default = getattr(value, "default", None)
        if default is not PydanticUndefined:
            return default
        return fallback

    def _safe_close(self, conn: imaplib.IMAP4 | imaplib.IMAP4_SSL) -> None:
        """Close IMAP connection, trying logout as fallback for non-compliant servers."""
        try:
            conn.close()
        except (Exception, _IMAP_EXCEPTION):
            with suppress(Exception, _IMAP_EXCEPTION):
                conn.logout()

    def _select_folder(self, conn: imaplib.IMAP4 | imaplib.IMAP4_SSL, folder: str, readonly: bool = False) -> None:
        """Select an IMAP folder, raising on failure (server returns NO).

        imaplib.select() does NOT raise on "NO" responses — it returns ("NO", ...).
        We need to check the status because subsequent commands will fail with
        "illegal in state AUTH" if the folder wasn't actually selected.
        """
        status, _ = conn.select(_quote(folder), readonly=readonly)
        is_ok = status.strip() == b"OK" if isinstance(status, bytes) else str(status).strip().upper() == "OK"
        if not is_ok:
            raise _IMAP_EXCEPTION(f"Failed to select folder '{folder}'")

    def _resolve_folder(self, folder: str) -> str:
        """Return the effective folder name.

        Folder is required — no silent fallback to INBOX or valve config.
        Raises ValueError if folder is None, empty, or not a string.
        """
        if not isinstance(folder, str) or not folder:
            raise ValueError("Folder parameter is required and cannot be empty or None.")
        return folder

    def _normalize_uids(self, param: Any) -> list[str]:
        """Accept str | list[str] | FieldInfo, always return a list of UID strings.

        Handles Pydantic FieldInfo wrapping from Open WebUI and comma-separated UID strings.
        """
        resolved = self._resolve_fieldinfo(param, None)
        if resolved is None:
            return []
        if isinstance(resolved, str):
            # Handle comma-separated UIDs (e.g., "1,2,3")
            return [u.strip() for u in resolved.split(",") if u.strip()]
        return [str(u) for u in resolved]

    def _fetch_emails_by_uid(self, conn: imaplib.IMAP4 | imaplib.IMAP4_SSL, uids: list[str]) -> list[dict]:
        """Fetch and parse multiple emails by UID. Returns list of parsed dicts."""
        results = []
        for uid in uids:
            try:
                _, raw_data = conn.uid("fetch", uid, "(RFC822)")
            except Exception:
                continue
            if not raw_data or len(raw_data) == 0:
                continue
            try:
                raw_bytes = raw_data[0][1]
                parsed = self._parse_email(raw_bytes)
                parsed["uid"] = uid
                results.append(parsed)
            except Exception:
                continue
        return results

    async def list_emails(
        self,
        folder: str,
        count: int = Field(default=10, description="Number of recent emails to list (default: 10)"),
    ) -> str:
        """
        List emails in a specific IMAP folder. Requires explicit folder name — no fallback.
        """
        count = self._resolve_fieldinfo(count, 10)
        folder = self._resolve_fieldinfo(folder, None)
        if not self.valves.username or not self.valves.password:
            return "Error: IMAP credentials (username and password) are not configured in Valves."
        if not self.valves.imap_server:
            return "Error: IMAP server is not configured in Valves."

        target_folder = self._resolve_folder(folder)

        try:
            conn = self._connect()
            self._select_folder(conn, target_folder, readonly=True)

            uid_map = self._refresh_uid_index(conn)

            if not uid_map:
                self._safe_close(conn)
                return "Folder is empty. No emails found."

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

            self._safe_close(conn)

            total_count = len(uid_map)

            result_lines = [f"Folder '{target_folder}': {total_count} total message(s)\n"]
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

    async def read_emails(
        self,
        uids: str | list[str] = Field(
            description="IMAP UID(s) to read. Accepts a single UID string (e.g. '42') or "
            "a comma-separated list of UIDs (e.g. '42,100,205')."
        ),
        folder: str = Field(description="IMAP folder to read from (required — no fallback)"),
    ) -> str:
        """
        Read specific email(s) by their IMAP UID(s).
        """
        if not self.valves.username or not self.valves.password:
            return "Error: IMAP credentials (username and password) are not configured in Valves."
        if not self.valves.imap_server:
            return "Error: IMAP server is not configured in Valves."

        target_folder = self._resolve_folder(self._resolve_fieldinfo(folder, None))

        try:
            conn = self._connect()
            self._select_folder(conn, target_folder, readonly=True)

            uids_list = self._normalize_uids(uids)

            if not uids_list:
                self._safe_close(conn)
                return "Error: No UIDs provided. Specify at least one email UID."

            emails = self._fetch_emails_by_uid(conn, uids_list)
            self._safe_close(conn)

            if not emails:
                return f"No emails found for the specified UID(s) in '{target_folder}'."

            results = []
            for parsed in emails:
                attachment_info = ""
                if parsed["has_attachments"]:
                    attachment_info = f"\n  Attachments: {parsed['attachment_count']} file(s) attached"

                section = (
                    f"=== Email [{parsed['uid']}] in '{target_folder}' ===\n"
                    f"  From:      {parsed['from']}\n"
                    f"  To:        {parsed['to']}\n"
                    f"  Subject:   {parsed['subject']}\n"
                    f"  Date:      {parsed['date']}\n"
                    f"  UID:       {parsed['uid']}\n"
                    f"  Message-ID:{parsed['message_id']}\n"
                    f"{attachment_info}\n"
                    f"  --- Body ---\n"
                    f"  {parsed['body']}"
                )
                results.append(section)

            return "\n---\n".join(results)

        except _IMAP_EXCEPTION as e:
            return f"IMAP Error: {str(e)}"
        except Exception as e:
            return f"Error reading emails: {str(e)}"

    async def search_emails(
        self,
        query: str = Field(
            description="Search query to filter emails. Supports 'from:<sender>', 'subject:<text>', 'before:<YYYY-MM-DD>', 'after:<YYYY-MM-DD>'"
        ),
        count: int = Field(default=10, description="Maximum number of results to return (default: 10)"),
        folder: str = Field(description="IMAP folder to search in (required — no fallback)"),
    ) -> str:
        """
        Search emails in the mailbox by sender, subject, or date range.
        :param query: Search criteria (e.g., 'from:alice@example.com', 'subject:invoice', 'after:2025-01-01')
        :param count: Maximum number of results
        :param folder: IMAP folder to search in (required, no fallback)
        """
        count = self._resolve_fieldinfo(count, 10)
        query = self._resolve_fieldinfo(query, "")
        if not self.valves.username or not self.valves.password:
            return "Error: IMAP credentials (username and password) are not configured in Valves."
        if not self.valves.imap_server:
            return "Error: IMAP server is not configured in Valves."

        target_folder = self._resolve_folder(self._resolve_fieldinfo(folder, None))

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
            self._select_folder(conn, target_folder, readonly=True)

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
                self._safe_close(conn)
                return f"No emails found matching criteria: {query}"

            uid_string = uid_data[0].decode("utf-8").strip()
            if not uid_string:
                self._safe_close(conn)
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
                            parsed["uid"] = uid
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
                        if parsed is not None:
                            parsed["uid"] = uid
                            matches.append(parsed)
                    except Exception:
                        continue
                    else:
                        continue

            self._safe_close(conn)

            if not matches:
                return f"No emails found matching criteria: {query}"

            result_lines = [f"Folder '{target_folder}': Found {len(matches)} email(s) matching: {query}\n"]
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
                    f"  UID:     {email_data.get('uid', '')}\n"
                    f"  Body:    {body_preview}"
                )

            return "\n".join(result_lines)

        except _IMAP_EXCEPTION as e:
            return f"IMAP Error: {str(e)}"
        except Exception as e:
            return f"Error searching emails: {str(e)}"

    async def delete_emails(
        self,
        uids: str | list[str] = Field(
            description="IMAP UID(s) to permanently delete. Accepts a single UID string (e.g. '42') or "
            "a comma-separated list of UIDs. WARNING: This is irreversible — emails cannot be recovered."
        ),
        folder: str = Field(description="IMAP folder to delete from (required — no fallback)"),
    ) -> str:
        """
        Permanently delete email(s) by their IMAP UID(s).
        """
        if not self.valves.allow_delete_single:
            return (
                "Delete operations are disabled. Enable 'allow_delete_single' in Valves. "
                "Permanent deletion is blocked for safety—to move email(s) to Trash instead, use ``move_emails`` with ``target_folder`` "
                "set to your trash folder (e.g. 'Trash' or 'Deleted Items')."
            )
        if not self.valves.username or not self.valves.password:
            return "Error: IMAP credentials (username and password) are not configured in Valves."
        if not self.valves.imap_server:
            return "Error: IMAP server is not configured in Valves."

        target_folder = self._resolve_folder(self._resolve_fieldinfo(folder, None))
        uids_list = self._normalize_uids(uids)

        try:
            conn = self._connect()
            self._select_folder(conn, target_folder)

            deleted: list[str] = []
            failed: list[tuple[str, str]] = []
            for uid in uids_list:
                try:
                    conn.uid("store", uid, "+FLAGS", "(\\Deleted)")
                    conn.expunge()
                    deleted.append(uid)
                except Exception as e:
                    failed.append((uid, str(e)))

            self._safe_close(conn)

            parts = []
            if len(deleted) == 1:
                parts.append(f"Email [{deleted[0]}] permanently deleted from '{target_folder}'.")
            elif deleted:
                parts.append(f"{len(deleted)} email(s) permanently deleted from '{target_folder}'.")
                parts.append(f"UIDs deleted: {', '.join(deleted)}")

            if failed:
                parts.append(f"Failed on {len(failed)} UID(s): {', '.join(u for u, _ in failed)}")

            result = "\n".join(parts) if len(parts) > 1 else parts[0]
            return result

        except _IMAP_EXCEPTION as e:
            return f"IMAP Error: {str(e)}"
        except Exception as e:
            return f"Error deleting emails: {str(e)}"

    async def delete_all_emails(
        self,
        folder: str = Field(description="IMAP folder to delete all emails from (required — no fallback)"),
    ) -> str:
        """
        Permanently delete **all** emails from a mailbox folder.

        This permanently removes every message — they are not moved to trash,
        and cannot be recovered. Use ``move_emails`` for reversible batch moves instead.

        :param folder: IMAP folder to delete all emails from (required, no fallback).
        """
        if not self.valves.allow_delete_all:
            return (
                "Delete-all operations are disabled. Enable 'allow_delete_all' in Valves. "
                "Permanent deletion of all emails is blocked for safety—to move emails in bulk, use ``move_emails`` to move them to "
                "Trash or another folder."
            )
        if not self.valves.username or not self.valves.password:
            return "Error: IMAP credentials (username and password) are not configured in Valves."
        if not self.valves.imap_server:
            return "Error: IMAP server is not configured in Valves."

        target_folder = self._resolve_folder(self._resolve_fieldinfo(folder, None))

        try:
            conn = self._connect()
            self._select_folder(conn, target_folder)

            uid_map = self._refresh_uid_index(conn)

            if not uid_map:
                self._safe_close(conn)
                return f"Mailbox '{target_folder}' is already empty. No emails to delete. To move emails to trash instead, use ``move_emails`` with ``target_folder`` set to your trash folder."

            uid_list = list(uid_map.keys())
            for uid in uid_list:
                conn.uid("store", uid, "+FLAGS", "(\\Deleted)")

            conn.expunge()
            self._safe_close(conn)
            return f"All {len(uid_list)} email(s) in '{target_folder}' have been deleted successfully."

        except _IMAP_EXCEPTION as e:
            return f"IMAP Error: {str(e)}"
        except Exception as e:
            return f"Error deleting emails: {str(e)}"

    async def move_emails(
        self,
        uids: str | list[str] = Field(
            description="IMAP UID(s) to move. Accepts a single UID string (e.g. '42') or "
            "a comma-separated list of UIDs (e.g. '42,100')."
        ),
        target_folder: str = Field(description="Target IMAP folder for the moved emails"),
        folder: str = Field(description="Source IMAP folder (required, no fallback)"),
    ) -> str:
        """
        Move email(s) from one IMAP folder to another by UID.
        """
        if not self.valves.allow_move:
            return "Move operations are disabled. Enable 'allow_move' in Valves to use this feature."
        if not self.valves.username or not self.valves.password:
            return "Error: IMAP credentials (username and password) are not configured in Valves."
        if not self.valves.imap_server:
            return "Error: IMAP server is not configured in Valves."

        source_folder = self._resolve_folder(self._resolve_fieldinfo(folder, None))
        uids_list = self._normalize_uids(uids)

        try:
            conn = self._connect()
            self._select_folder(conn, source_folder)

            # Ensure target folder exists
            with suppress(_IMAP_EXCEPTION):
                conn.create(_quote(target_folder))

            moved: list[str] = []
            failed: list[tuple[str, str]] = []
            for uid in uids_list:
                try:
                    conn.uid("COPY", uid, _quote(target_folder))
                    conn.uid("STORE", uid, "+FLAGS", "(\\Deleted)")
                    conn.expunge()
                    moved.append(uid)
                except Exception as e:
                    failed.append((uid, str(e)))

            self._safe_close(conn)

            parts = []
            if len(moved) == 1:
                parts.append(f"Email [{moved[0]}] moved from '{source_folder}' to '{target_folder}' successfully.")
            elif moved:
                parts.append(f"{len(moved)} email(s) moved from '{source_folder}' to '{target_folder}'.")
                parts.append(f"UIDs moved: {', '.join(moved)}")

            if failed:
                parts.append(f"Failed on {len(failed)} UID(s): {', '.join(u for u, _ in failed)}")

            result = "\n".join(parts) if len(parts) > 1 else parts[0]
            return result

        except _IMAP_EXCEPTION as e:
            return f"IMAP Error: {str(e)}"
        except Exception as e:
            return f"Error moving emails: {str(e)}"

    async def create_folder(
        self, folder: str = Field(description="Name of the new IMAP folder to create (e.g., 'Projects/Invoices')")
    ) -> str:
        """Create a new IMAP folder/mailbox."""
        if not self.valves.allow_create_folder:
            return "Create folder operations are disabled. Enable 'allow_create_folder' in Valves to use this feature."
        if not self.valves.username or not self.valves.password:
            return "Error: IMAP credentials (username and password) are not configured in Valves."
        if not self.valves.imap_server:
            return "Error: IMAP server is not configured in Valves."

        try:
            conn = self._connect()
            conn.create(_quote(folder))
            self._select_folder(conn, folder, readonly=True)
            self._safe_close(conn)
            return f"Folder '{folder}' has been created successfully."

        except _IMAP_EXCEPTION as e:
            return f"IMAP Error: {str(e)}. Check if the folder name is valid."
        except Exception as e:
            return f"Error creating folder '{folder}': {str(e)}"

    async def delete_folder(
        self, folder: str = Field(description="Name of the folder to delete (must be empty)")
    ) -> str:
        """Delete an existing IMAP folder (must be empty)."""
        if not self.valves.allow_delete_folder:
            return "Delete folder operations are disabled. Enable 'allow_delete_folder' in Valves to use this feature."
        if not self.valves.username or not self.valves.password:
            return "Error: IMAP credentials (username and password) are not configured in Valves."
        if not self.valves.imap_server:
            return "Error: IMAP server is not configured in Valves."

        try:
            conn = self._connect()
            conn.delete(_quote(folder))
            self._safe_close(conn)
            return f"Folder '{folder}' has been deleted successfully."

        except _IMAP_EXCEPTION as e:
            return f"IMAP Error: {str(e)}. Check if the folder exists and is empty."
        except Exception as e:
            return f"Error deleting folder '{folder}': {str(e)}"

    async def list_folders(self) -> str:
        """List all available IMAP folders/mailboxes on the server.

        This is a read-only operation — no valve toggle required.
        """
        if not self.valves.username or not self.valves.password:
            return "Error: IMAP credentials (username and password) are not configured in Valves."
        if not self.valves.imap_server:
            return "Error: IMAP server is not configured in Valves."

        try:
            conn = self._connect()
            _, folders_data = conn.list()
            self._safe_close(conn)

            if not folders_data:
                return "No folders found on the IMAP server."

            lines = ["Available IMAP folders:"]
            for entry in folders_data:
                if entry is None:
                    continue
                try:
                    decoded = entry.decode("utf-8")
                    lines.append(f"  {decoded}")
                except (UnicodeDecodeError, AttributeError):
                    lines.append(f"  {entry}")

            return "\n".join(lines)

        except _IMAP_EXCEPTION as e:
            return f"IMAP Error: {str(e)}. Check your credentials and server settings."
        except Exception as e:
            return f"Error listing folders: {str(e)}"
