"""Auto-generated test module."""

import poplib
from unittest.mock import MagicMock, patch

import pytest

from pop3_mailbox import Tools


class TestPOP3SearchInnerLoop:
    """Test search_emails inner loop exception paths and date exclusions."""

    @pytest.mark.asyncio
    async def test_search_inner_loop_exception_continue(self):
        # T1-LOOP-EXCEPTION-CONTINUE
        # Given a POP3 mailbox with three emails where one raises on fetch
        # When the tool searches with no criteria
        # Then the two successfully-fetched emails are returned and the failing one is skipped
        t = Tools()
        t.valves.username = "user"
        t.valves.password = "pass"
        t.valves.pop3_server = "pop3.example.com"

        mock_server = MagicMock()
        mock_server.stat.return_value = (3, 3000)
        mock_server.quit.return_value = None

        call_order = []
        emails = [
            b"From: a@b.com\r\nTo: c@d.com\r\nSubject: OK1\r\nDate: Mon, 21 Apr 2025 10:00:00 +0000\r\n\r\nBody1",
            b"From: e@f.com\r\nTo: g@h.com\r\nSubject: OK2\r\nDate: Mon, 21 Apr 2025 11:00:00 +0000\r\n\r\nBody2",
            b"From: i@j.com\r\nTo: k@l.com\r\nSubject: OK3\r\nDate: Mon, 21 Apr 2025 12:00:00 +0000\r\n\r\nBody3",
        ]

        def mock_retr(index):
            call_order.append(index)
            if index == 2:
                raise RuntimeError("inner fetch error")
            array_idx = index - 1
            if 0 <= array_idx < len(emails):
                lines = emails[array_idx].split(b"\r\n")
                return ("220 OK", lines, len(emails[array_idx]))
            raise poplib.error_proto("no message")

        mock_server.retr.side_effect = mock_retr

        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await t.search_emails(query="", count=10)
        assert "Found 2 email(s)" in result and "OK3" in result and "OK1" in result and "OK2" not in result

    @pytest.mark.asyncio
    async def test_search_inner_loop_exception_date_parsing(self):
        # T1-RED-4
        # Given a POP3 email with an unparseable date string
        # When the tool searches with date filters
        # Then that email is excluded from the filtered result
        t = Tools()
        t.valves.username = "user"
        t.valves.password = "pass"
        t.valves.pop3_server = "pop3.example.com"

        mock_server = MagicMock()
        mock_server.stat.return_value = (2, 2000)
        mock_server.quit.return_value = None

        good_email = (
            b"From: e@f.com\r\nTo: g@h.com\r\nSubject: Good\r\nDate: Mon, 21 Apr 2025 10:00:00 +0000\r\n\r\nBody"
        )
        bad_date_email = b"From: a@b.com\r\nTo: c@d.com\r\nSubject: BadDate\r\nDate: not-a-valid-date\r\n\r\nBody"

        def mock_retr(index):
            if index == 2:
                lines = good_email.split(b"\r\n")
                return ("220 OK", lines, len(good_email))
            elif index == 1:
                lines = bad_date_email.split(b"\r\n")
                return ("220 OK", lines, len(bad_date_email))
            raise poplib.error_proto("no message")

        mock_server.retr.side_effect = mock_retr

        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await t.search_emails(query="after:2020-01-01", count=10)
        assert "Good" in result and "BadDate" not in result

    @pytest.mark.asyncio
    async def test_search_early_break(self):
        # T1-LOOP-EARLY-BREAK
        # Given a POP3 mailbox with five matching emails
        # When the tool searches with no criteria and count=2
        # Then only the two newest emails are returned and the loop breaks early
        t = Tools()
        t.valves.username = "user"
        t.valves.password = "pass"
        t.valves.pop3_server = "pop3.example.com"

        mock_server = MagicMock()
        mock_server.stat.return_value = (5, 5000)
        mock_server.quit.return_value = None

        emails = []
        for i in range(1, 6):
            email = (
                b"From: a@b.com\r\nTo: c@d.com\r\nSubject: Match"
                + str(i).encode()
                + b"\r\nDate: Mon, 21 Apr 2025 10:00:00 +0000\r\n\r\nBody"
            )
            emails.append(email)

        call_count = [0]

        def mock_retr(index):
            call_count[0] += 1
            email_idx = index - 1
            if 0 <= email_idx < len(emails):
                lines = emails[email_idx].split(b"\r\n")
                return ("220 OK", lines, len(emails[email_idx]))
            raise poplib.error_proto("no message")

        mock_server.retr.side_effect = mock_retr

        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await t.search_emails(query="", count=2)
        assert "Found 2 email(s)" in result and "Match5" in result and "Match4" in result and "Match3" not in result

    @pytest.mark.asyncio
    async def test_search_after_exclusion(self):
        # T1-LOOP-AFTER-EXCLUSION
        # Given two POP3 emails, one dated inside the after: range and one dated before it
        # When the tool searches with an after: filter
        # Then the in-range email is returned
        # And the pre-range email is not returned
        t = Tools()
        t.valves.username = "user"
        t.valves.password = "pass"
        t.valves.pop3_server = "pop3.example.com"

        mock_server = MagicMock()
        mock_server.stat.return_value = (2, 2000)
        mock_server.quit.return_value = None

        good_email = (
            b"From: e@f.com\r\nTo: g@h.com\r\nSubject: Good\r\nDate: Mon, 21 Apr 2025 10:00:00 +0000\r\n\r\nBody"
        )
        old_email = (
            b"From: a@b.com\r\nTo: c@d.com\r\nSubject: Old\r\nDate: Mon, 1 Jan 2019 10:00:00 +0000\r\n\r\nOld body"
        )

        def mock_retr(index):
            if index == 2:
                lines = good_email.split(b"\r\n")
                return ("220 OK", lines, len(good_email))
            elif index == 1:
                lines = old_email.split(b"\r\n")
                return ("220 OK", lines, len(old_email))
            raise poplib.error_proto("no message")

        mock_server.retr.side_effect = mock_retr

        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await t.search_emails(query="after:2020-01-01", count=10)
        assert "Good" in result and "Old" not in result

    @pytest.mark.asyncio
    async def test_search_before_exclusion(self):
        # T1-LOOP-BEFORE-EXCLUSION
        # Given two POP3 emails, one dated inside the before: range and one dated after it
        # When the tool searches with a before: filter
        # Then the in-range email is returned
        # And the post-range email is not returned
        t = Tools()
        t.valves.username = "user"
        t.valves.password = "pass"
        t.valves.pop3_server = "pop3.example.com"

        mock_server = MagicMock()
        mock_server.stat.return_value = (2, 2000)
        mock_server.quit.return_value = None

        good_email = (
            b"From: e@f.com\r\nTo: g@h.com\r\nSubject: Good\r\nDate: Mon, 21 Apr 2025 10:00:00 +0000\r\n\r\nBody"
        )
        future_email = b"From: a@b.com\r\nTo: c@d.com\r\nSubject: Future\r\nDate: Mon, 31 Dec 2030 10:00:00 +0000\r\n\r\nFuture body"

        def mock_retr(index):
            if index == 2:
                lines = good_email.split(b"\r\n")
                return ("220 OK", lines, len(good_email))
            elif index == 1:
                lines = future_email.split(b"\r\n")
                return ("220 OK", lines, len(future_email))
            raise poplib.error_proto("no message")

        mock_server.retr.side_effect = mock_retr

        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await t.search_emails(query="before:2026-01-01", count=10)
        assert "Good" in result and "Future" not in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
