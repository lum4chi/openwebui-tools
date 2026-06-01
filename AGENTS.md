# AGENTS.md

## Repo structure

Each `.py` file in the root is a standalone Open WebUI Workspace Tool — not a library. Import via Workspace → Tools → Import.

Tool spec: https://docs.openwebui.com/features/extensibility/plugin/tools/

Existing tools (importable as separate tools):
- `imap_mailbox.py` — IMAP mailbox + ManageSieve filter manager
- `pop3_mailbox.py` — POP3 mailbox reader

## Engineering Principles

### Write minimal code
- **DRY — but not dogmatically**: extract only when reuse is obvious. A little duplication is cheaper than forced abstractions.
- **No inheritance**: each tool's `Tools` class is flat — no base classes, no mixins.

### Keep files small
Each tool file must stay in **a single `*.py`** (Open WebUI imports a single file).
Test files should be organized in subfolders with helper classes if they grow large.

### Meaningful tests at high coverage
**100% coverage required** (`fail_under = 100` in `pyproject.toml`):

- **Test behaviour, not implementation**: assert return values, raised exceptions, state changes — not mock call counts.
- **Test edge cases**: empty inputs, single items, boundary values, error paths.
- **One assertion group per test**: use `@pytest.mark.parametrize` for repeated scenarios.

## Tool format (non-negotiable)

Every tool must have:

1. **Top-level docstring** with Open WebUI metadata:
   ```python
   """
   title: Tool Name
   author: Your Name
   author_url: https://...
   description: One-line description
   requirements:
   version: 1.0.0
   licence: MIT
   required_open_webui_version: 0.5.0
   """
   ```

2. **`Tools` class** with async methods and type hints:
   ```python
   class Tools:
       def __init__(self):
           self.valves = self.Valves()
           self.citation = False

       class Valves(BaseModel):
           server: str = Field(default="", description="Server host")

       async def list_emails(self, count: int = Field(default=10)) -> str:
           """Docstring describes the tool for the model."""
   ```

## Commands

```bash
uv sync                          # install deps
uv run ruff format .             # format first (can change code)
uv run ruff check .              # lint after format
uv run pyright                   # type check
uv run pytest -v --cov           # tests with coverage
```

**CI order**: `format → check → pyright → test`. Running format after check is pointless — format then lint.

## Lint rules (ruff)

- Line length: 120 (E501 ignored; ruff format handles this)
- Select: E, W, F, I, N, UP, B, SIM, T201
- Ignore: E501, B008, **E402** (`module level import not at top of file` — needed when test files reorder imports like `from ...test_common import ...`)
- Use `X | None` not `Optional[X]` (py311+)
- Use `contextlib.suppress` instead of `try/except: pass`
- Rename unused loop vars to `_` prefix (e.g., `_idx`)

## Testing

- Tests go in `tests/<tool_name>/` subdirectories
- **No `@pytest.mark.asyncio` needed**: `asyncio_mode = "auto"` in `pyproject.toml`
- Mock with `unittest.mock.MagicMock` + `patch` — no real mail server
- Set valves on fixture instances; don't set on bare `Tools()` unless testing defaults
- **Maximum 300 lines per test file**: when a test file exceeds this limit, split it into multiple files by feature/operation. Name files `test_<feature>.py` or `test_<operation>.py`. Move shared fixtures to `conftest.py`.

## Email tool implementation notes

### IMAP (`imap_mailbox.py`)
- Emails indexed **1-based, newest first** (index 1 = highest UID)
- Write operations gated by valve toggles that default to `False`
- `imaplib.IMAP4Exception` compatibility shim: `getattr(imaplib, "IMAP4Exception", Exception)`
- **Mock**: `imaplib.IMAP4_SSL` / `imaplib.IMAP4`
- RFC822 fetch payload: `[prefix_bytes, raw_bytes]` (two-element list)
- `list_emails` **requires** `folder`; `read_email` and `search_emails` accept optional `folder`
- `_resolve_folder(folder)` returns `folder` if truthy, otherwise valve config or `"INBOX"`

### POP3 (`pop3_mailbox.py`)
- Emails indexed **1-based, newest first** (highest server index)
- No folder concept — all operations on the single mailbox
- **Mock**: `poplib.POP3_SSL` / `poplib.POP3`
- `retr()` returns `[status, [line1, line2, ...], size]` (three-element list)

### Write operation valves
- `allow_delete_single` — delete one email at a time
- `allow_delete_all` — delete every email in a folder
- `allow_move` — covers both general moves AND archive (archive is just move to a configured folder)
- `allow_create_folder`, `allow_delete_folder` — folder management
- Sieve valves: `allow_create/update/delete/activate_sieve` (all `False` by default)

## pyright config

Uses `basic` type checking mode (`pyrightconfig.json`): relaxes unknown parameter/member/argument types. Don't be surprised by missing type errors on partially-typed code.

## Commit convention

[Conventional Commits](https://www.conventionalcommits.org/): `feat:`, `fix:`, `test:`, `docs:`, `style:`, `chore:`

Format: `<type>: <description>` or `<type>: <description>\n\n<body>`

## Versioning

`version` in each tool's docstring follows SemVer. Bump when changing that tool:
- **Patch**: bug fixes
- **Minor**: new features/methods (non-breaking)
- **Major**: breaking API changes (new required params, removed methods)
