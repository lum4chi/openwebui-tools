# Open WebUI Tools

Custom tools for [Open WebUI](https://github.com/open-webui/open-webui).

Each `.py` file is a standalone tool. Import via Workspace → Tools → Import.

## Available Tools

### IMAP Mailbox Manager

Manage a generic IMAP mailbox with folder access.

#### Features

- **List emails** - View recent messages with sender, subject, date, UID, and body preview
- **Read email** - Retrieve full email content by index (folder-aware)
- **Search emails** - Filter by sender (`from:`), subject (`subject:`), date (`after:`, `before:`), or free text (folder-aware)
- **Get count** - Check total mailbox size
- **Delete email** - Remove individual messages or all messages (gated by valves)
- **Archive email** - Move messages to archive folder (gated by valves)
- **Move email** - Move messages between any folders (gated by valves)
- **Folder access** - Separate toggles for archive, trash, sent, drafts folders
- **Folder param override** - All list/read/search methods accept optional `folder` parameter

#### Installation

1. Copy `imap_mailbox.py` into your Open WebUI tools directory, or import it via:
   - Open WebUI → **Workspace** → **Tools** → **Import**
   - Paste the file content or provide a URL

2. Configure your IMAP credentials in the tool's **Valves**:

   | Setting | Default | Description |
   |---------|---------|-------------|
   | `imap_server` | `""` | IMAP server hostname |
   | `imap_port` | `993` | Port (993 for SSL, 143 for non-SSL) |
   | `username` | `""` | Mailbox username |
   | `password` | `""` | Mailbox password or app-specific password |
   | `use_ssl` | `True` | Enable SSL/TLS |
   | `timeout` | `30` | Connection timeout in seconds |
   | `inbox_folder` | `INBOX` | Default inbox folder name |
   | `archive_folder` | `Archive` | Archive folder path |
   | `trash_folder` | `Trash` | Trash folder path |
   | `sent_folder` | `Sent` | Sent folder path |
   | `drafts_folder` | `Drafts` | Drafts folder path |

    Write-access toggles (default `False`):
    - `allow_delete_single`, `allow_delete_all`, `allow_move`

3. Enable the tool for your model:
   - Go to **Workspace** → **Models** → select your model → **Tools**
   - Check "IMAP Mailbox Manager"

#### Usage Examples

```
# List the 5 most recent emails
list_emails(folder="INBOX", count=5)

# Read email at index 1 (most recent by UID)
read_email(email_index=1)

# Search by sender or free text
search_emails(query="from:alice@example.com", count=10)

# Search with date range
search_emails(query="after:2025-01-01 before:2025-04-01", count=10)

# List emails from a custom folder
list_emails(count=5, folder="Custom/Folder")

# Archive an email (requires allow_move valve)
archive_email(email_index=1)

# Delete an email (requires allow_delete_single valve)
delete_email(email_index=1)

# Move an email to another folder (requires allow_move valve)
move_email(email_index=1, target_folder="Projects", folder="INBOX")

### POP3 Mailbox Reader

Read and search emails from any generic POP3 mailbox.

#### Features

- **List emails** - View recent messages with sender, subject, date, and body preview
- **Read email** - Retrieve full email content by index
- **Search emails** - Filter by sender (`from:`), subject (`subject:`), or date range (`after:`, `before:`)
- **Get count** - Check total mailbox size

#### Installation

1. Copy `pop3_mailbox.py` into your Open WebUI tools directory, or import it via:
   - Open WebUI → **Workspace** → **Tools** → **Import**
   - Paste the file content or provide a URL

2. Configure your POP3 credentials in the tool's **Valves**:

   | Setting | Default | Description |
   |---------|---------|-------------|
   | `pop3_server` | `localhost` | POP3 server hostname |
   | `pop3_port` | `995` | Port (995 for SSL, 110 for plain) |
   | `username` | `""` | Mailbox username |
   | `password` | `""` | Mailbox password or app-specific password |
   | `use_ssl` | `True` | Enable SSL/TLS |
   | `timeout` | `30` | Connection timeout in seconds |

3. Enable the tool for your model:
   - Go to **Workspace** → **Models** → select your model → **Tools**
   - Check "POP3 Mailbox Reader"

#### Usage Examples

```
# List the 5 most recent emails
list_emails(folder="INBOX", count=5)

# Read email at index 1 (most recent)
read_email(email_index=1)

# Search by sender
search_emails(query="from:alice@example.com", count=10)

# Search by subject
search_emails(query="subject:invoice", count=10)

# Search by date range
search_emails(query="after:2025-01-01 before:2025-04-01", count=10)

### YouTube Manager

Personal YouTube digest: gathers candidates from Watch Later and subscribed channels via the YouTube Data API and manages the digest playlist.

#### Features

- **Check setup** - `check_setup` verifies the Google OAuth set (live token check only when the set is complete)
- **Start auth** - `start_auth` prints the Google consent URL for the youtube scope
- **Finish auth** - `finish_auth` exchanges the pasted code/redirect URL and stores the refresh token to a local credential file (automatic; no manual storage)
- **Gather candidates** - `gather_candidates` from `watch_later`, `search`, or `subscriptions` sources (comma-separated)
- **Watch Later source** - `watch_later` gathers from the user-maintained playlist named by the `watch_later_playlist_title` valve (default `Watch Later`), not the hidden system playlist
- **Digest** - `digest` aggregates candidates, feedback stats, and source status into the LLM-facing digest
- **List playlists** - `list_playlists` enumerates the channel's playlists
- **Add to playlist** - `add_to_playlist` inserts a video into the managed digest playlist
- **Prune playlist** - `prune_playlist` enforces the digest playlist policy caps
- **Transcript** - `transcript` fetches a video transcript (youtube-transcript-api, yt-dlp fallback)
- **Save taste profile** - `save_taste_profile` stores the Markdown taste profile passed verbatim to the digest
- **Record feedback** - `record_feedback` appends a `watched` / `listened` / `skipped` row to the feedback log

#### Installation

1. Copy `youtube_manager.py` into your Open WebUI tools directory, or import it via:
   - Open WebUI → **Workspace** → **Tools** → **Import**
   - Paste the file content or provide a URL

2. Configure the tool's **Valves**:

   | Setting | Default | Description |
   |---------|---------|-------------|
   | `google_client_id` | `""` | Google OAuth client ID (installed-app, Production-mode client) |
   | `google_client_secret` | `""` | Google OAuth client secret |
   | `digest_playlist_title` | `Open WebUI Digest` | Title of the managed digest playlist (resolved by exact title match; created if absent) |
   | `watch_later_playlist_title` | `Watch Later` | User-maintained playlist used as the Watch Later source (resolved by exact trimmed title match; 0 candidates if absent) |
   | `digest_max_items` | `50` | Policy cap: keep at most the newest N tool-added items |
   | `digest_max_age_days` | `30` | Policy cap: drop tool-added items older than D days |
   | `verbose` | `False` | Include raw HTTP error detail in source notes |

   Per-user credential file: `finish_auth` stores the acquired refresh token in `data/<user_id>/google-refresh-token.md` (one file per Open WebUI user). The file is the ONLY credential source; the tool resolves it itself - when it is absent or stale, a tool method reports `REAUTH_NEEDED` and the `start_auth` / `finish_auth` flow acquires and stores a new token.

3. Enable the tool for your model:
   - Go to **Workspace** → **Models** → select your model → **Tools**
   - Check "YouTube Manager"

#### Usage Examples

```
# Setup / auth flow
check_setup()
start_auth()
finish_auth(code_or_url="https://127.0.0.1:33333/oauth2callback?code=4/...")

# Gather candidates (comma-separated sources)
gather_candidates(sources="watch_later,subscriptions")
gather_candidates(sources="search", search_query="rust async")

# Playlists
list_playlists()

# Transcript
transcript(video_id="dQw4w9WgXcQ")
```

#### Live acceptance harness (dev-only)

```bash
cp env.template .env
# fill in the YTM_* values in .env (keep .env uncommitted)
uv run python dev/youtube_live.py
```

The tool itself reads Valves, never env vars — env vars are a dev-harness concern only.

Re-auth: to re-auth after a credential change, delete `.data-live/<user_id>/google-refresh-token.md` and re-run; the token-reuse guard otherwise skips the browser flow while that file exists.

## Development

Requires Python ≥3.11. Uses [uv](https://github.com/astral-sh/uv) for dependency management.

Run order matters for CI: `ruff check -> ruff format -> pyright -> pytest`.

#### Setup

```bash
# Install dependencies
uv sync

# Run tests
uv run pytest -v

# Run linter
uv run ruff check .

# Auto-fix lint issues
uv run ruff check --fix .

# Format code
uv run ruff format .

# Run type checker
uv run pyright
```

## License

MIT
