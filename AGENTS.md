# AGENTS.md

## Repo structure

Each `.py` file in the root is a standalone Open WebUI Workspace Tool — not a library or app. Tools are imported into Open WebUI via Workspace → Tools → Import.

Tool spec: https://docs.openwebui.com/features/extensibility/plugin/tools/

## Tool format (non-negotiable)

Every tool must have:

1. **Top-level docstring** with Open WebUI metadata fields:
   ```
   """
   title: Tool Name
   author: Your Name
   author_url: https://...
   description: One-line description
   requirements: comma, separated, deps
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
           self.citation = False  # disable auto-citations if using custom ones

       class Valves(BaseModel):
           server: str = Field(default="", description="POP3 host")
           port: int = Field(default=995, description="POP3 port")

       async def list_emails(self, count: int = Field(default=10)) -> str:
           """Docstring describes the tool for the model."""
   ```

3. **Type hints required** — no type hints = poor model tool selection. Use `int`, `str`, `str | None`, `list[str]`, etc.

4. **Async methods** — use `async def` for future compatibility.

5. **Valves** for config — use `pydantic.BaseModel` with `Field()`. Users edit these in Open WebUI UI.

## Commands

```bash
uv sync                          # install deps
uv run pytest -v                 # run tests
uv run ruff check .              # lint
uv run ruff check --fix .        # auto-fix lint
uv run ruff format .             # format
uv run pyright                   # type check
```

Order matters for CI: `ruff check -> ruff format -> pyright -> pytest`.

## Lint rules (ruff)

- Line length: 120
- Enabled: E, W, F, I, N, UP, B, SIM, T201
- Ignored: E501 (line length), B008 (call in arg default)
- Trailing whitespace is an error (W291)
- Unused imports are errors (F401)
- Use `X | None` not `Optional[X]` (py311+)
- Use `contextlib.suppress` instead of `try/except: pass`
- Rename unused loop vars to `_` prefix (e.g., `_idx`)

## Testing

- Tests go in `test_<tool_name>.py` alongside the tool
- Mock the POP3 server with `unittest.mock.MagicMock` — no real server needed
- Tests use `@pytest.mark.asyncio` for async tool methods

## Commit convention

Use [Conventional Commits](https://www.conventionalcommits.org/):

- `feat:` new tool or feature
- `fix:` bug fix or type error resolution
- `test:` test additions or changes
- `docs:` README, AGENTS.md, or other documentation
- `style:` formatting, trailing whitespace, unused imports
- `chore:` deps, config, CI, project setup

Format: `<type>: <description>` or `<type>: <description>\n\n<body>`

## Adding a new tool

1. Create `<tool_name>.py` in the root with the docstring + `Tools` class format above
2. Create `test_<tool_name>.py` with mocked tests
3. Run `uv run ruff check . && uv run pyright && uv run pytest -v` — all must pass
4. Update README.md with installation and usage instructions
