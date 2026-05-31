# AGENTS.md

## Repo structure

Each `.py` file in the root is a standalone Open WebUI Workspace Tool — not a library or app. Import via Workspace → Tools → Import.

Tool spec: https://docs.openwebui.com/features/extensibility/plugin/tools/

Existing tools (both importable as separate tools):
- `imap_mailbox.py` — IMAP mailbox + ManageSieve filter manager
- `pop3_mailbox.py` — POP3 mailbox reader

## Engineering Principles

These principles govern how code is written in this project. They are as important as the lint rules.

### Write minimal code

- **DRY — but not dogmatically**: extract shared logic only when reuse is obvious, not forced. A little duplication is cheaper than an abstraction that doesn't fit.
- **Prefer composition over inheritance**: each tool's `Tools` class is a flat module — no base classes, no mixins.
- **No premature optimization**: write the simple solution first. Optimize only when a concrete bottleneck is measured.

### Keep files and classes small

Every tool file should stay **as short as possible** but it must be just one file, because way openwebui import tools just as single `*.py`.
Test file need instead to be organized and manageable: move related methods to a new helper class, pull a repeated logic block into a private function, or split into a new file. If a method exceeds is too long, refactor before finishing.

### Meaningful tests at high coverage

The project enforces **99.9%** test coverage (`fail_under = 99.9` in `pyproject.toml`). Coverage alone is not enough — tests must be **meaningful**:

- **Test behaviour, not implementation**: assert on observable outcomes (return values, raised exceptions, state changes), not on how many times a mock was called.
- **Test edge cases**: empty inputs, single-item inputs, boundary values, error paths — not just the happy path.
- **Each test does one thing**: one `assert_perfect` or one clear assertion group per test function.
- **Use parametrized tests** (`@pytest.mark.parametrize`) for repeated scenarios instead of copy-pasting test functions.
- **Never assert on mock call counts** unless the call pattern itself is the behaviour under test.

## Tool format (non-negotiable)

Every tool must have:

1. **Top-level docstring** with Open WebUI metadata fields:
   ```
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

2. **`Tools` class** with async methods and type hints on all parameters:
    ```python
    class Tools:
        def __init__(self):
            self.valves = self.Valves()
            self.citation = False

        class Valves(BaseModel):
            server: str = Field(default="", description="Mail server host")
            port: int = Field(default=993, description="Server port")

        async def list_emails(self, count: int = Field(default=10)) -> str:
            """Docstring describes the tool for the model."""
    ```

3. **Type hints required** — no type hints = poor model tool selection. Use `int`, `str`, `str | None`, `list[str]`, etc.
4. **Async methods** — use `async def`.
5. **Valves** for config — use `pydantic.BaseModel` with `Field()`.

## Commands

```bash
uv sync                          # install deps
uv run pytest -v --cov           # run tests with coverage
uv run ruff check .              # lint
uv run ruff check --fix .        # auto-fix lint
uv run ruff format .             # format
uv run pyright                   # type check
```

CI order: `ruff check -> ruff format -> pyright -> pytest -v --cov`.

## Lint rules (ruff)

- Line length: 120
- Select: E, W, F, I, N, UP, B, SIM, T201
- Ignore: E501, B008
- Trailing whitespace is an error (W291)
- Unused imports are errors (F401)
- Use `X | None` not `Optional[X]` (py311+)
- Use `contextlib.suppress` instead of `try/except: pass`
- Rename unused loop vars to `_` prefix (e.g., `_idx`)

## Testing

See **Engineering Principles > Meaningful tests** for test quality guidelines.

- Tests go in `tests/test_<tool_name>.py`
- Mock with `unittest.mock.MagicMock` + `patch` — no real mail server needed
- Tests use `@pytest.mark.asyncio`
- Set tool valves on fixture instances; don't set them on bare `Tools()` unless testing defaults
- Email index is **1-based, newest first**. For IMAP, "newest" = highest UID. For POP3, "newest" = highest server index.

## Email tool implementation notes

- Both IMAP and POP3 tools use UID/index ordering where index 1 = most recent email (highest UID for IMAP, highest server index for POP3)
- Write operations (delete, archive) are gated by valve toggles that default to `False` for safety
- IMAP uses `imaplib.IMAP4Exception` compatibility shim for older Python (`getattr(imaplib, "IMAP4Exception", Exception)`)
- Mock the correct connection class: `imaplib.IMAP4_SSL` / `imaplib.IMAP4` for IMAP, `poplib.POP3_SSL` / `poplib.POP3` for POP3
- IMAP RFC822 fetch responses wrap payload as `[prefix_bytes, raw_bytes]`; POP3 `retr()` returns `[status, [line1, line2, ...], size]`
- IMAP has per-folder access guards (`allow_list_archive`, `allow_list_trash`, etc.); POP3 does not (no folder concept)
- `list_emails` requires `folder`; `read_email` and `search_emails` accept optional `folder` param (use `list_inbox_emails`/`read_inbox_email` for no-folder variant)
- `pyright` config uses `basic` type checking mode with missing types relaxed

## Commit convention

Use [Conventional Commits](https://www.conventionalcommits.org/):

- `feat:` new tool or feature
- `fix:` bug fix or type error resolution
- `test:` test additions or changes
- `docs:` README, AGENTS.md, or other documentation
- `style:` formatting, trailing whitespace, unused imports
- `chore:` deps, config, CI, project setup

Format: `<type>: <description>` or `<type>: <description>\n\n<body>`

## Versioning

The `version` field in each tool's docstring follows [Semantic Versioning](https://semver.org/): `MAJOR.MINOR.PATCH`.

- **Patch** (`1.0.0 → 1.0.1`): bug fixes — bump on `fix:` commits
- **Minor** (`1.0.x → 1.1.0`): new features/methods — bump on `feat:` commits
- **Major** (`1.x.x → 2.0.0`): breaking API changes

Update `version:` in the tool's top-level docstring when bumping.

## Adding a new tool

1. Create `<tool_name>.py` in the root with the docstring + `Tools` class format above. Keep it as short as possible but it must be just one `*.py` file.
2. Create `tests/test_<tool_name>.py` with mocked tests — use `@pytest.mark.parametrize` for repeated scenarios. Split cases in multiple files in order to keep them manageable.
3. Run `uv run ruff check . && uv run pyright && uv run pytest -v --cov` — coverage must be **≥ 99.9%** and all checks pass.
4. Update README.md and AGENTS.md accordingly.
