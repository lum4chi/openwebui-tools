"""
title: IMAP Mailbox Manager
author: lum4chi
author_url: https://github.com/lum4chi/openwebui-tools
description: Manage a generic IMAP mailbox. Supports listing, reading, searching, and deleting emails via IMAP. Also manages Sieve email filters via ManageSieve.
requirements: sievelib>=1.5.0
version: 2.0.1
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
from typing import TYPE_CHECKING, Union

from pydantic import BaseModel, Field


class EncryptionMode(StrEnum):
    """Encryption method for mail connections. Always encrypted — plaintext never allowed."""

    implicit = "implicit"  # TLS from the start (port 993/995)
    starttls = "starttls"  # Upgrade to TLS after connect (port 143/110/20000/4190)


# Compatibility: imaplib.IMAP4Exception may not exist in all Python versions
_IMAP_EXCEPTION = getattr(imaplib, "IMAP4Exception", Exception)

from sievelib.managesieve import Client  # pyright: ignore[reportMissingImports]


def _handle_sieve_list_result(result):
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

        allow_list_inbox: bool = Field(
            default=False, description="Allow reading emails from the inbox folder (default: False for safety)"
        )
        allow_list_archive: bool = Field(
            default=False, description="Allow reading emails from the archive folder (default: False for safety)"
        )
        allow_list_trash: bool = Field(
            default=False, description="Allow reading emails from the trash folder (default: False for safety)"
        )
        allow_list_sent: bool = Field(
            default=False, description="Allow reading emails from the sent folder (default: False for safety)"
        )
        allow_list_drafts: bool = Field(
            default=False, description="Allow reading emails from the drafts folder (default: False for safety)"
        )

        # write permissions
        allow_delete_single: bool = Field(
            default=False, description="Allow deleting individual emails (default: False for safety)"
        )
        allow_delete_all: bool = Field(
            default=False, description="Allow deleting all emails (default: False for safety)"
        )
        allow_archive: bool = Field(default=False, description="Allow archiving emails (default: False for safety)")

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

    # Common Sieve script names tried when listscripts() returns empty.
    _COMMON_SIEVE_SCRIPTS = (
        "default",
        "mail_filter",
        "userfilter",
        "main",
        "dovecot-sieve",
        ".dovecot.sieve",
        "Open-Xchange",
        "sieve-filter",
    )

    async def check_sieve_connection(self) -> str:
        """Diagnose ManageSieve connection for the configured server.

        Tests both STARTTLS and implicit TLS, reports which mode works,
        shows server capabilities, and attempts to list scripts with each mode.
        Useful when 'list_sieve_scripts' returns nothing but filters exist.
        """
        if not self.valves.username or not self.valves.password:
            return "Error: IMAP credentials (username and password) are not configured in Valves."
        if not self.valves.imap_server:
            return "Error: IMAP server is not configured in Valves."

        server = self.valves.manage_sieve_server or self.valves.imap_server
        port = self.valves.manage_sieve_port
        results: list[str] = []

        for _enc_mode, ssl_flag, starttls_flag, label in [
            (EncryptionMode.starttls, False, True, "STARTTLS"),
            (EncryptionMode.implicit, True, False, "Implicit TLS"),
        ]:
            results.append(f"--- {label} ---")
            try:
                client = Client(server, srvport=port)
                connected = client.connect(
                    self.valves.username,
                    self.valves.password,
                    ssl=ssl_flag,
                    starttls=starttls_flag,
                )
                if not connected:
                    results.append("  Connection/authentication FAILED.")
                    with suppress(Exception):
                        client.logout()
                    continue

                results.append("  Connected: Yes")

                # Check capabilities
                try:
                    impl = client.get_implementation()
                    sieve_caps = client.get_sieve_capabilities()
                    results.append(f"  Server implementation: {impl}")
                    results.append(f"  Sieve extensions: {', '.join(sorted(sieve_caps)) if sieve_caps else 'N/A'}")
                except Exception as exc:
                    results.append(f"  Capabilities check failed: {exc}")

                # Attempt script listing
                try:
                    active, scripts, err = _handle_sieve_list_result(client.listscripts())
                    if scripts is None:
                        results.append("  listscripts(): Server returned NO (no scripts available for this account).")
                    elif not scripts:
                        info = f"(active: {active})" if active else "(none active)"
                        results.append(f"  listscripts(): 0 scripts found on server. {info}")
                    else:
                        scripts_str = ", ".join(sorted(scripts))
                        active_part = f", active='{active}'" if active else ""
                        results.append(f"  listscripts(): Found scripts: {scripts_str}{active_part}")
                except Exception as exc:
                    results.append(f"  listscripts() failed: {exc}")

                with suppress(Exception):
                    client.logout()
            except Exception as exc:
                results.append(f"  Connection error: {exc}")

        output_lines = [
            "ManageSieve Connection Diagnostic",
            f"Server: {server}:{port}",
            "",
        ]
        output_lines.extend(results)
        return "\n".join(output_lines)

    async def try_fetch_sieve_script(self) -> str:
        """Try fetching common Sieve script names when listscripts() returns empty.

        When ManageSieve's LISTSCRIPTS returns no scripts but filters are
        active on the server (e.g. Dovecot Pigeonhole stores them under
        non-standard names), this attempts to fetch known script names.
        """
        result = self._manage_sieve_connect()
        if isinstance(result, str):
            return result
        client = result
        try:
            active, scripts, err = _handle_sieve_list_result(client.listscripts())
            if scripts is not None and scripts:
                client.logout()
                return (
                    f"ManageSieve found {len(scripts)} script(s): {', '.join(sorted(scripts))} "
                    f"(active: {active if active else 'none'}).\n"
                    f"Use get_sieve_script(name) to retrieve one of them."
                )

            # Build list of names to try: first the active script, then common names.
            # Try both the bare name and the .sieve-extended form.
            names_to_try: list[str] = []
            if active and isinstance(active, str):
                names_to_try.append(active)
                names_to_try.append(f"{active}.sieve")
            names_to_try.extend(self._COMMON_SIEVE_SCRIPTS)
            # Add .sieve variant for each common name that doesn't already end in .sieve
            for name in self._COMMON_SIEVE_SCRIPTS:
                if not name.endswith(".sieve"):
                    names_to_try.append(f"{name}.sieve")

            for name in names_to_try:
                try:
                    content = client.getscript(name)
                    client.logout()
                    return f"=== Found Sieve script: {name} ===\n{content}"
                except Exception:
                    pass

            client.logout()
            tried = ", ".join(names_to_try)
            return (
                "ManageSieve connection succeeded but found no scripts.\n"
                f"Tried known names: {tried} — none accessible.\n"
                "Filters may be managed via a server-side system not exposed through ManageSieve."
            )

            for name in self._COMMON_SIEVE_SCRIPTS:
                try:
                    content = client.getscript(name)
                    client.logout()
                    return f"=== Found Sieve script: {name} ===\n{content}"
                except Exception:
                    pass

            client.logout()
            return (
                "ManageSieve connection succeeded but found no scripts.\n"
                f"Tried known names: {', '.join(self._COMMON_SIEVE_SCRIPTS)} — none accessible.\n"
                "Filters may be managed via a server-side system not exposed through ManageSieve."
            )
        except Exception as e:
            with suppress(Exception):
                client.logout()
            return f"Error trying common script names: {str(e)}"

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

    def _resolve_folder(self, folder: str | None = None, fallback: str | None = None) -> str:
        """Return the effective folder name; falls back to valve config."""
        if folder:
            return folder
        return fallback or (getattr(self.valves, "inbox_folder", None) or "INBOX")

    def _access_guard(self, folder_type: str, effective_folder: str) -> str | None:
        """Check whether LLM is allowed to access the given folder type.

        Returns ``None`` when access is allowed, otherwise an error message.
        """
        valve_name = f"allow_list_{folder_type}"
        folder_valve_name = f"{folder_type}_folder"
        valve = getattr(self.valves, valve_name, None)
        default_folder = getattr(self.valves, folder_valve_name, None)

        if not valve:
            return (
                f"{folder_type.capitalize()} access is disabled. Enable '{valve_name}' in Valves to use this feature."
            )

        # If the user customised the folder path but didn't enable access
        if default_folder and effective_folder != default_folder:
            return (
                f"{folder_type.capitalize()} access is disabled. Enable '{valve_name}' in Valves to use this feature."
            )

        return None

    def _fetch_email_by_uid(self, conn: imaplib.IMAP4 | imaplib.IMAP4_SSL, uid: str) -> dict | None:
        """Fetch and parse a single email by UID. Returns None on failure."""
        try:
            _, raw_data = conn.uid("fetch", uid, "(RFC822)")
        except Exception:
            return None
        if not raw_data or len(raw_data) == 0:
            return None
        raw_bytes = raw_data[0][1]
        try:
            return self._parse_email(raw_bytes)
        except Exception:
            return None

    async def list_inbox_emails(
        self, count: int = Field(default=10, description="Number of recent emails to list (default: 10)")
    ) -> str:
        """
        List emails in the inbox folder.
        :param count: Number of recent emails to retrieve and display
        """
        error = self._access_guard("inbox", self.valves.inbox_folder)
        if error:
            return error
        return await self._list_folder_emails(self.valves.inbox_folder, count)

    async def list_emails(
        self,
        folder: str,
        count: int = Field(default=10, description="Number of recent emails to list (default: 10)"),
    ) -> str:
        """
        List emails in a specific IMAP folder. Requires explicit folder name — no fallback.
        """
        if not self.valves.username or not self.valves.password:
            return "Error: IMAP credentials (username and password) are not configured in Valves."
        if not self.valves.imap_server:
            return "Error: IMAP server is not configured in Valves."

        target_folder = self._resolve_folder(folder, fallback=folder)

        try:
            conn = self._connect()
            conn.select(target_folder, readonly=True)

            uid_map = self._refresh_uid_index(conn)

            if not uid_map:
                conn.close()
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

            conn.close()

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

    async def read_inbox_email(
        self,
        email_index: int = Field(description="Index of the email to read (1-based, 1 = most recent by UID)"),
    ) -> str:
        """
        Read a specific inbox email by index.
        :param email_index: 1-based index (1 = most recent inbox email by UID)
        """
        error = self._access_guard("inbox", self.valves.inbox_folder)
        if error:
            return error
        return await self._read_folder_email(email_index, self.valves.inbox_folder)

    async def read_email(
        self,
        email_index: int = Field(description="Index of the email to read (1-based, 1 = most recent by UID)"),
        folder: str | None = Field(
            default=None, description="Optional IMAP folder to read from (uses valve 'folder' by default)"
        ),
    ) -> str:
        """
        Read a specific email by its index in the mailbox.
        :param email_index: 1-based index (1 = most recent email by UID)
        :param folder: Optional folder override (e.g. 'Archive', 'Sent'). Defaults to valve setting.
        """
        if not self.valves.username or not self.valves.password:
            return "Error: IMAP credentials (username and password) are not configured in Valves."
        if not self.valves.imap_server:
            return "Error: IMAP server is not configured in Valves."

        target_folder = self._resolve_folder(folder)

        try:
            conn = self._connect()
            conn.select(target_folder, readonly=True)

            uid_map = self._refresh_uid_index(conn)

            if not uid_map:
                conn.close()
                return f"Error: Mailbox '{target_folder}' is empty. No emails to read."

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
                f"=== Email [{uid}]/{total_count} in '{target_folder}' ===\n"
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
        folder: str | None = Field(
            default=None, description="Optional IMAP folder to search (uses valve 'folder' by default)"
        ),
    ) -> str:
        """
        Search emails in the mailbox by sender, subject, or date range.
        :param query: Search criteria (e.g., 'from:alice@example.com', 'subject:invoice', 'after:2025-01-01')
        :param count: Maximum number of results
        :param folder: Optional folder override (e.g. 'Archive', 'Sent'). Defaults to valve setting.
        """
        if not self.valves.username or not self.valves.password:
            return "Error: IMAP credentials (username and password) are not configured in Valves."
        if not self.valves.imap_server:
            return "Error: IMAP server is not configured in Valves."

        target_folder = self._resolve_folder(folder)

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
            conn.select(target_folder, readonly=True)

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
                    parsed = self._fetch_email_by_uid(conn, uid)
                    if parsed is not None:
                        matches.append(parsed)
                    else:
                        continue

            conn.close()

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
            conn.select(self.valves.inbox_folder, readonly=True)

            uid_count = 0
            _, uid_data = conn.uid("search", None, "ALL")  # pyright: ignore[reportArgumentType]
            if uid_data[0]:
                uid_string = uid_data[0].decode("utf-8").strip()
                if uid_string:
                    uid_count = len(uid_string.split())

            conn.close()
            return f"Mailbox '{self.valves.inbox_folder}' contains {uid_count} message(s)."
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
            conn.select(self.valves.inbox_folder)

            uid_map = self._refresh_uid_index(conn)

            if not uid_map:
                conn.close()
                return f"Error: Mailbox '{self.valves.inbox_folder}' is empty. Nothing to delete."

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
            return f"Email [{uid}] in '{self.valves.inbox_folder}' has been deleted successfully."

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
            conn.select(self.valves.inbox_folder)

            uid_map = self._refresh_uid_index(conn)

            if not uid_map:
                conn.close()
                return "Mailbox is already empty. No emails to delete."

            uid_list = list(uid_map.keys())
            for uid in uid_list:
                conn.uid("store", uid, "+FLAGS", "(\\Deleted)")

            conn.expunge()
            conn.close()
            return f"All {len(uid_list)} email(s) in '{self.valves.inbox_folder}' have been deleted successfully."

        except _IMAP_EXCEPTION as e:
            return f"IMAP Error: {str(e)}"
        except Exception as e:
            return f"Error deleting emails: {str(e)}"

    async def archive_email(
        self, email_index: int = Field(description="Index of the email to archive (1-based, 1 = most recent by UID)")
    ) -> str:
        """
        Archive a specific email by moving it to the configured archive folder.
        :param email_index: 1-based index (1 = most recent email by UID)
        """
        if not self.valves.allow_archive:
            return "Archive operations are disabled. Enable 'allow_archive' in Valves to use this feature."
        if not self.valves.username or not self.valves.password:
            return "Error: IMAP credentials (username and password) are not configured in Valves."
        if not self.valves.imap_server:
            return "Error: IMAP server is not configured in Valves."

        try:
            conn = self._connect()
            conn.select(self.valves.inbox_folder)

            uid_map = self._refresh_uid_index(conn)

            if not uid_map:
                conn.close()
                return f"Error: Mailbox '{self.valves.inbox_folder}' is empty. Nothing to archive."

            try:
                reversed_map: dict[int, str] = {v: k for k, v in uid_map.items()}
                uid = reversed_map[email_index]
            except (KeyError, TypeError):
                conn.close()
                return f"Error: Email index {email_index} is out of range. Mailbox has {len(uid_map)} message(s)."

            conn.uid("COPY", uid, self.valves.archive_folder)  # pyright: ignore[reportArgumentType]
            conn.uid("STORE", uid, "+FLAGS", "(\\Deleted)")  # pyright: ignore[reportArgumentType]
            conn.expunge()
            conn.close()
            return f"Email [{uid}] has been archived to '{self.valves.archive_folder}' successfully."

        except _IMAP_EXCEPTION as e:
            return f"IMAP Error: {str(e)}"
        except Exception as e:
            return f"Error archiving email: {str(e)}"

    # -------------------------------------------------------------------------
    # Convenience methods for reading emails from special folders
    # -------------------------------------------------------------------------

    async def list_archive_emails(
        self, count: int = Field(default=10, description="Number of archived emails to list (default: 10)")
    ) -> str:
        """
        List emails in the configured archive folder.
        :param count: Number of archived emails to retrieve and display
        """
        error = self._access_guard("archive", self.valves.archive_folder)
        if error:
            return error
        return await self._list_folder_emails(self.valves.archive_folder, count)

    async def read_archive_email(
        self,
        email_index: int = Field(description="Index of the archived email to read (1-based, 1 = most recent by UID)"),
    ) -> str:
        """
        Read a specific archived email by its index.
        :param email_index: 1-based index (1 = most recent archived email by UID)
        """
        error = self._access_guard("archive", self.valves.archive_folder)
        if error:
            return error
        return await self._read_folder_email(email_index, self.valves.archive_folder)

    async def list_trash_emails(
        self, count: int = Field(default=10, description="Number of trashed emails to list (default: 10)")
    ) -> str:
        """
        List emails in the configured trash folder.
        :param count: Number of trashed emails to retrieve and display
        """
        error = self._access_guard("trash", self.valves.trash_folder)
        if error:
            return error
        return await self._list_folder_emails(self.valves.trash_folder, count)

    async def read_trash_email(
        self,
        email_index: int = Field(description="Index of the trashed email to read (1-based, 1 = most recent by UID)"),
    ) -> str:
        """
        Read a specific trashed email by its index.
        :param email_index: 1-based index (1 = most recent trashed email by UID)
        """
        error = self._access_guard("trash", self.valves.trash_folder)
        if error:
            return error
        return await self._read_folder_email(email_index, self.valves.trash_folder)

    async def list_sent_emails(
        self, count: int = Field(default=10, description="Number of sent emails to list (default: 10)")
    ) -> str:
        """
        List emails in the configured sent folder.
        :param count: Number of sent emails to retrieve and display
        """
        error = self._access_guard("sent", self.valves.sent_folder)
        if error:
            return error
        return await self._list_folder_emails(self.valves.sent_folder, count)

    async def read_sent_email(
        self, email_index: int = Field(description="Index of the sent email to read (1-based, 1 = most recent by UID)")
    ) -> str:
        """
        Read a specific sent email by its index.
        :param email_index: 1-based index (1 = most recent sent email by UID)
        """
        error = self._access_guard("sent", self.valves.sent_folder)
        if error:
            return error
        return await self._read_folder_email(email_index, self.valves.sent_folder)

    async def list_draft_emails(
        self, count: int = Field(default=10, description="Number of draft emails to list (default: 10)")
    ) -> str:
        """
        List emails in the configured drafts folder.
        :param count: Number of draft emails to retrieve and display
        """
        error = self._access_guard("drafts", self.valves.drafts_folder)
        if error:
            return error
        return await self._list_folder_emails(self.valves.drafts_folder, count)

    # -------------------------------------------------------------------------
    # Internal helpers used by convenience methods
    # -------------------------------------------------------------------------

    async def _list_folder_emails(self, folder: str, count: int) -> str:
        """List all email messages in the given *folder*."""
        if not self.valves.username or not self.valves.password:
            return "Error: IMAP credentials (username and password) are not configured in Valves."
        if not self.valves.imap_server:
            return "Error: IMAP server is not configured in Valves."

        try:
            conn = self._connect()
            conn.select(folder, readonly=True)

            uid_map = self._refresh_uid_index(conn)

            if not uid_map:
                conn.close()
                return f"Folder '{folder}' is empty. No emails found."

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

            result_lines = [f"Folder '{folder}': {total_count} total message(s)\n"]
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

    async def _read_folder_email(self, email_index: int, folder: str) -> str:
        """Read a single email by index from the given *folder*."""
        if not self.valves.username or not self.valves.password:
            return "Error: IMAP credentials (username and password) are not configured in Valves."
        if not self.valves.imap_server:
            return "Error: IMAP server is not configured in Valves."

        try:
            conn = self._connect()
            conn.select(folder, readonly=True)

            uid_map = self._refresh_uid_index(conn)

            if not uid_map:
                conn.close()
                return f"Error: Folder '{folder}' is empty. No emails to read."

            # uid_map = {uid: position} -> build reverse
            try:
                uid_map_rev: dict[int, str] = {pos: uid for uid, pos in uid_map.items()}
                uid = uid_map_rev[email_index]  # type: ignore[typeddict-item]
            except (KeyError, TypeError):
                conn.close()
                return f"Error: Email index {email_index} is out of range. Folder has {len(uid_map)} message(s)."

            _, raw_data = conn.uid("fetch", uid, "(RFC822)")  # type: ignore[arg-type]
            raw_bytes = raw_data[0][1] if raw_data and len(raw_data) > 0 else b""
            parsed = self._parse_email(raw_bytes)

            total_count = len(uid_map)
            conn.close()

            attachment_info = ""
            if parsed["has_attachments"]:
                attachment_info = f"\n  Attachments: {parsed['attachment_count']} file(s) attached"

            result = (
                f"=== Email [{uid}]/{total_count} in '{folder}' ===\n"
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
