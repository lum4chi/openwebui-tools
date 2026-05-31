"""Auto-generated test module."""

import email as _email_module
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import pytest


class TestIMAPDecodeMIMECharsetErrors:
    """Test _decode_mime_header charset decode failure paths (lines 357-358)."""

    @pytest.mark.asyncio
    async def test_decode_mime_header_lookup_error(self, tools):
        """Test _decode_mime_header with invalid charset triggers LookupError fallback (lines 357-358)."""
        # create_header_value with an unusual charset that triggers LookupError
        result = tools._decode_mime_header("=?invalidx?Q?testvalue?=")
        assert "testvalue" in result or "invalidx" in result.lower()

    @pytest.mark.asyncio
    async def test_decode_mime_header_unicode_decode_error(self, tools):
        """Test _decode_mime_header with bytes that fail in declared charset (lines 357-358)."""
        result = tools._decode_mime_header("=?iso-8859-1?Q?=E9test?=")
        assert "test" in result.lower() or "E9" in result


class TestIMAPGetBodyCharsetErrors:
    """Test _get_email_body charset decode error paths (lines 377-378, 385-386)."""

    @pytest.mark.asyncio
    async def test_get_email_body_multipart_lookup_error(self, tools):
        """Test multipart body with LookupError/UnicodeDecodeError during decode (lines 377-378)."""

        class BadPart(MIMEText):
            def get_content_charset(self):
                return "nonexistent-charset-xyz-123"

            def get_payload(self, decode=False):
                if decode:
                    return b"\x80\x81\x82\xff"
                return "inner"

        msg = MIMEMultipart()
        msg.attach(BadPart("inner"))
        tools._get_email_body(msg)

    @pytest.mark.asyncio
    async def test_get_email_body_non_multipart_decode_error(self, tools):
        """Test non-multipart body extraction with charset decode error (lines 385-386)."""
        msg = _email_module.message_from_string("Content-Type: text/plain; charset=nonexistent-xyz-123\r\n\r\n")

        def mock_get_payload(decode=False):
            if decode:
                return b"\xff\xfe\x00\x01"
            return None

        msg.get_payload = mock_get_payload
        result = tools._get_email_body(msg)
        # Should handle decode error gracefully without crashing
        assert isinstance(result, str)
