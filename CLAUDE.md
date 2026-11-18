# CLAUDE.md

Guidance for Claude sessions working on this repository.

## Branches (important)

| Branch | Purpose |
|--------|---------|
| `main` | **Official branch.** Only tested, release-ready code. Final builds come from here. |
| `dev`  | **Working branch.** All development and testing happens here. |

Rules:

- **Always work on `dev`.** At the start of every session, check out `dev` and commit and push there, even if the session was started on an automatically created branch such as `claude/...`. This instruction is the owner's explicit permission to push to `dev`. Don't create or push to session or feature branches.
  ```bash
  git fetch origin dev && git checkout dev && git pull --ff-only origin dev
  ```
  If the session started on another branch that already has commits not on `dev`, bring them over (`git checkout dev && git merge --no-edit <that-branch>`) instead of losing them.
- **Never commit or push to `main` directly.** `main` is only updated by merging `dev` into it, and only when the owner explicitly asks for a release or merge. Before merging, all tests must pass on `dev`.
- Never force-push `main` or `dev`.

## Project

File-Converter is an **offline** desktop file converter (Windows first, later macOS and Linux).
The whole point of the project is **data safety**: files never leave the user's device.
The roadmap is in `docs/PROJECT_PLAN.md`, and the user-facing promises are in `PRIVACY.md`.

Stack: Python 3.11+, PySide6 (GUI), Pillow and pillow-heif (images), PyMuPDF and pdf2docx (PDF),
LibreOffice headless (office formats), PyInstaller (Windows build). License: GPL-3.0-or-later.

## Non-negotiable rules for the code

- **No network access.** No telemetry, analytics, crash reporting, online APIs or automatic update checks. Don't add dependencies that phone home. Engines run with network features disabled (see the LibreOffice hardened profile in `converters/office.py`).
- **Never modify originals, and never overwrite existing files** unless the user asks (`overwrite=True`). Use `engine.unique_path`.
- **Temporary files** go only into the per-job folder the engine provides (`ctx.work_dir`), which is always deleted.
- **Photo metadata** (EXIF/GPS) is stripped by default.
- Untrusted input: catch engine errors and raise `ConversionError` with a message a non-technical user understands.

## Layout

```
src/fileconv/
  formats.py          format list and detection by file content
  engine.py           route finding (multi-step), running jobs, temp folders
  converters/base.py  Converter plugin interface
  converters/*.py     images, pdf, office plugins; register new ones in converters/__init__.py
  cli.py              `fileconv` command line
  gui/                PySide6 window
tests/                pytest; conftest.py blocks all network access in every test
packaging/            PyInstaller spec (FileConverter.exe + fileconv.exe)
```

To add a format family, write a new `Converter` subclass with `capabilities()` and `convert()`,
register it, and add tests. The engine, CLI and GUI pick it up automatically.

## Commands

```bash
pip install -e ".[dev]"
```

```bash
pytest
```

```bash
ruff check src tests && ruff format --check src tests
```

```bash
python -m fileconv
```

```bash
cd packaging && pyinstaller fileconv.spec --noconfirm
```

`python -m fileconv` without arguments opens the GUI; with arguments it runs the CLI.
GUI tests need `QT_QPA_PLATFORM=offscreen` on headless machines (set in `conftest.py`).
Office tests are skipped when LibreOffice isn't installed. Install it to run them.

## Before every commit

- `pytest` passes and `ruff` is clean.
- New features come with tests.
- Update `docs/PROJECT_PLAN.md` checkboxes and the README's format table when features change.
