"""Auto-generated test module."""

from unittest.mock import patch

import pytest

from .conftest import _make_mock_server


class TestPOP3ReadEmailIndexZero:
    """Test read_email with index=0 (boundary validation)."""

    @pytest.mark.asyncio
    async def test_read_email_index_zero(self, tools):
        """Test that read_email rejects index=0 as out of range."""
        mock_server = _make_mock_server(2, [])
        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await tools.read_email(email_index=0)
        assert "out of range" in result.lower()

    @pytest.mark.asyncio
    async def test_read_email_negative_index(self, tools):
        """Test that read_email rejects negative index as out of range."""
        mock_server = _make_mock_server(2, [])
        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await tools.read_email(email_index=-1)
        assert "out of range" in result.lower()
