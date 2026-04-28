# Open WebUI Tools

Custom tools for [Open WebUI](https://github.com/open-webui/open-webui).

## Available Tools

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
list_emails(count=5)

# Read email at index 1 (most recent)
read_email(email_index=1)

# Search by sender
search_emails(query="from:alice@example.com", count=10)

# Search by subject
search_emails(query="subject:invoice", count=10)

# Search by date range
search_emails(query="after:2025-01-01 before:2025-04-01", count=10)

# Check mailbox size
get_email_count()
```

## Development

This project uses [uv](https://github.com/astral-sh/uv) for dependency management.

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
