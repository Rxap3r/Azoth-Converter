# CLAUDE.md

Guidance for Claude sessions working on this repository.

## Current status (keep this section up to date)

Read this first in a new session. Details are in `docs/PROJECT_PLAN.md` and `CHANGELOG.md`.

- **Released:** Azoth Converter **0.1.0** (18 Nov 2026) on GitHub Releases (installer + portable
  ZIP). The repository is **public** at `Rxap3r/Azoth-Converter` (renamed from `File-Converter`;
  the old URL redirects, but connect new sessions to the new name).
- **GitHub setup:** a ruleset protects **only `main`** (pull request required, checks Tests
  (Linux), Tests (Windows) and Windows app required). `dev` accepts direct pushes. Dependabot
  alerts, private vulnerability reporting and two-factor authentication are on.
- **Waiting on the owner:** the SignPath Foundation code-signing application. Sequence:
  1. ✓ `CODE_SIGNING.md` is on `main` (pull request #5, merged 19 Nov 2026);
  2. **next:** the owner applies on signpath.org with the repo link and the link to `CODE_SIGNING.md`
     on `main`;
  3. after approval, the owner saves the SignPath API key as a GitHub secret (never in chat);
  4. then add signing to `.github/workflows/release.yml` / `.github/actions/build-windows`:
     build → sign the `.exe` files → build the installer → sign the installer, with manual
     approval per release in SignPath.
- **Version 0.2.0** prepared (19 Nov 2026): new look, PDF tools, remove photo metadata. The owner
  publishes it with the Release workflow after the pull request is merged. Later work goes
  under `CHANGELOG.md` → Unreleased. Not yet tried on a real Windows PC: the new look, and
  metadata removal with real phone photos.
- **Next planned work (owner decides the order):**
  - design refresh: slicker look, a remove button per file, icon rework (the seal looks like a
    smiley from afar), a cleaner "Supported formats" section;
  - PDF compress and passwords, then OCR (release 0.2; metadata tool and the first PDF tools
    are done);
  - agreed order (Nov 2026): metadata tool ✓ → split `gui/main_window.py` ✓ → design
    mockups ✓ → **style A built** ✓ (with Light / Dark / Follow Windows; not yet seen on a
    real Windows PC; icon choice postponed by the owner) → **PDF tools** ✓ (merge, split,
    edit pages; compress and passwords next) → OCR;
  - technical improvements: faster batches, smaller download;
  - a fully portable version.
- **Session limits:** sessions can push branches but **not tags**, which is why releases are
  created by the Release workflow. To get a test build of `dev`, start "Build and test" with
  `workflow_dispatch` on `dev` (the owner can also do it in the Actions tab).

## Working with the owner

- Explain things in plain, simple language; the owner isn't a professional developer. Avoid
  jargon or explain it ("CI" was renamed to "Build and test" for that reason).
- The owner trusts you with technical choices, but wants to be asked before pull requests,
  releases and anything that changes GitHub settings, workflows or rules.
- **Keep answers short** (owner's wish, Nov 2026): lead with the one thing that matters (result,
  question or next step), a few bullets at most, no long explanations unless asked.
- **Save tokens:** read only the parts of files you need (grep first, then a line range), but
  read enough of the surroundings to not miss problems. Make small edits instead of rewriting
  files. Screenshots only when the look changed, cropped to the part that changed.
- Priorities: data safety first, then **1:1 conversion quality**, then clean and efficient
  solutions. Never weaken tests or checks to save time.
- Write ideas and requests the owner mentions into `docs/PROJECT_PLAN.md` right away, so
  nothing gets lost between sessions.

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
- **Never commit or push to `main` directly.** `main` only changes through a **pull request from
  `dev` into `main` that the owner reviews and merges**. Never merge it yourself.
- **Before opening a pull request into `main`** (owner's wish, Nov 2026): check whether the
  changes since the last release are worth a release (new features or fixes users notice). If
  yes, first ask the owner whether to release; if they agree, prepare the release on `dev`
  (see "Releasing") and only then open one pull request, so `main` doesn't need a second one
  just for the version and notes.
- **Only open that pull request when the owner explicitly tells you to** (e.g. "pull it"). When
  work seems ready, you may ask whether they want a pull request, but wait for the go-ahead;
  a request for a release or a build is not a go-ahead for a pull request on its own.
- Never force-push `main` or `dev`.
- The **Build and test** workflow (`.github/workflows/build-and-test.yml`): every push to `dev` runs only the fast Linux tests; pull
  requests into `main`, pushes to `main` and manual runs also run the Windows tests and build
  and test the ~190 MB installer. Doc-only pushes (`docs/**`, `*.md`) start no run, but pull
  requests into `main` always get the full check, because the three checks (Tests (Linux),
  Tests (Windows), Windows app) are required before merging. Don't change this without asking.

## Releasing (only when the owner asks)

1. On `dev`: set the new version in `pyproject.toml` and `src/azoth/__init__.py`; in
   `CHANGELOG.md` rename **Unreleased** to `[<version>] - <date>`, add a new empty Unreleased
   section and update the links at the bottom; write the user-facing release notes in
   `docs/releases/v<version>.md` from `docs/releases/TEMPLATE.md`, based on that changelog
   section. Always keep the template's **Downloads** section, which explains the installer,
   the portable ZIP and GitHub's source-code archives. All tests must pass.
2. Ask the owner whether to open the pull request `dev` → `main`; open it only when they say
   so ("pull it"). "Build and test" runs the full check (Linux, Windows, installer). The owner merges it.
3. The owner starts **Actions → Release → Run workflow** on `main`. It checks the version and
   notes; runs all tests on Linux and Windows while building and testing the installer in
   parallel; and only when all of that passed, creates the tag `v<version>` and publishes the
   GitHub Release with exactly the tested installer and portable ZIP. No tag needs to be pushed.

## Project

Azoth Converter is an **offline** desktop file converter (Windows first, later macOS and Linux).
The whole point of the project is **data safety**: files never leave the user's device.
The roadmap is in `docs/PROJECT_PLAN.md`, and the user-facing promises are in `PRIVACY.md`.
Future ideas and change requests from the owner go into `docs/PROJECT_PLAN.md` as unchecked items
in the matching phase (design wishes under "Design refresh"); there is no separate wish list.

Stack: Python 3.11+, PySide6 (GUI), Pillow and pillow-heif (images), PyMuPDF and pdf2docx (PDF),
LibreOffice headless (office formats), PyInstaller (Windows build). License: GPL-3.0-or-later.

## Public repository

The repository is public. Never commit secrets, personal data or real user files (samples are
made up). Commits are authored as "Claude <noreply@anthropic.com>"; don't put the owner's
email or other personal details into commits, code or docs. Security reports go through
GitHub's private vulnerability reporting (see `SECURITY.md`), never public issues.

## Non-negotiable rules for the code

- **Quality: conversions as close to 1:1 as possible.** Prefer the highest-fidelity engine
  (e.g. Microsoft Word for Word → PDF when installed). Never re-compress or downscale when
  the target can hold the original data (photos in PDFs are embedded unchanged, lossless
  sources stay lossless). Lossy settings come from `quality.py`, whose minimums
  (`MIN_IMAGE_QUALITY`, `MIN_DPI`) must not be lowered. Add a test in `tests/test_quality.py`
  for every quality guarantee. Where loss is unavoidable, say so in `quality_note()`.

- **No network access.** No telemetry, analytics, crash reporting, online APIs or automatic update checks. Don't add dependencies that phone home. Engines run with network features disabled (see the LibreOffice hardened profile in `converters/office.py`).
- **Never modify originals, and never overwrite existing files** unless the user asks (`overwrite=True`). Use `engine.unique_path`.
- **Temporary files** go only into the per-job folder the engine provides (`ctx.work_dir`), which is always deleted.
- **Photo metadata** (EXIF/GPS) is stripped by default.
- **Clean uninstall.** The app may store data only in `gui/settings.storage_dir()`
  (`%APPDATA%\Azoth Converter`), never in the registry; job temp folders start with
  `engine.TEMP_PREFIX`. Anything new the app writes must be removed by `[UninstallDelete]` in
  `packaging/installer.iss` and checked by the "Test installer" step of the automatic build.
- Untrusted input: catch engine errors and raise `ConversionError` with a message a non-technical user understands.

## Layout

```
src/azoth/
  formats.py          format list and detection by file content
  engine.py           route finding (multi-step), running jobs, temp folders
  converters/base.py  Converter plugin interface
  converters/*.py     images, pdf, office plugins; register new ones in converters/__init__.py
  cli.py              `azoth` command line
  pdf_tools.py        merge, split, edit pages (lossless; used by the app and `azoth pdf`)
  metadata.py         show/remove photo metadata (`azoth clean`); byte-level code in converters/strip.py
  gui/                PySide6 app (design "A"): main_window.py = sidebar + pages, runs jobs;
                      convert_page.py (layout), file_list.py (file cards), target_picker.py
                      (format tiles), options_panel.py (quality), output_folder.py,
                      formats_panel.py, settings_page.py, pdf_tools_page.py (Merge / Split /
                      Edit pages), worker.py (background thread),
                      targets.py (which targets are offered, no Qt), theme.py (light/dark
                      colours + stylesheet; widgets only set a "role" property), icons.py
                      (line icons drawn from SVG), About dialog, settings.py (QSettings)
                      error_log.py (local error log + crash dump, Settings → Error log…)
  resources/          icon.png (drawn by packaging/make_icon.py)
tests/                pytest; conftest.py blocks all network access in every test
packaging/            PyInstaller spec (AzothConverter.exe + azoth.exe), installer.iss (Inno Setup),
                      make_icon.py; the automatic build creates and tests the installer
.github/workflows/    only two workflows: build-and-test.yml and release.yml (shown in the Actions tab)
.github/actions/      their shared steps: run-tests, build-windows (composite actions, not listed)
samples/              test files (Word, PDF, Excel, PowerPoint, images, problem files);
                      recreate with `python samples/generate.py`, see samples/README.md
```

To add a format family, write a new `Converter` subclass with `capabilities()` and `convert()`,
register it, and add tests. The engine, CLI and GUI pick it up automatically.

## Commands

```bash
pip install --require-hashes -r requirements-dev.lock
```

```bash
pip install --no-deps -e .
```

Library versions are locked (with hashes) in `requirements.lock` (app) and
`requirements-dev.lock` (app + test/build tools). The automatic tests and builds install from them, so every
build of a commit uses the same versions. After changing dependencies in `pyproject.toml`,
regenerate both files and commit them:

```bash
uv pip compile pyproject.toml --universal --python-version 3.12 --generate-hashes -o requirements.lock
```

```bash
uv pip compile pyproject.toml --extra dev --universal --python-version 3.12 --generate-hashes -o requirements-dev.lock
```

```bash
pytest
```

```bash
ruff check src tests && ruff format --check src tests
```

```bash
python -m azoth
```

```bash
cd packaging && pyinstaller azoth.spec --noconfirm
```

`python -m azoth` without arguments opens the GUI; with arguments it runs the CLI.
GUI tests need `QT_QPA_PLATFORM=offscreen` on headless machines (set in `conftest.py`).
Office tests are skipped when LibreOffice isn't installed. Install it to run them.

## Look and feel

All colours are in `gui/theme.py` (one set for light, one for dark); widgets never hard-code
colours, they set a `role` property that the stylesheet styles. `tests/test_theme.py` checks
every colour pair for readable contrast: keep it passing when colours change.

## Languages

The app and the installer always offer the same languages (currently English only). When adding
a translation to the app, add the matching Inno Setup language to `packaging/installer.iss` in the
same change, and never add an installer language the app doesn't have.

## Before every commit

- Add every user-visible or workflow change to `CHANGELOG.md` under **Unreleased** (short,
  plain sentences; sections Added / Changed / Fixed / Removed / Quality / Privacy and safety /
  Development).
- `pytest` passes and `ruff` is clean.
- New features come with tests.
- Update `docs/PROJECT_PLAN.md` checkboxes and the README's format table when features change.
- When conversions change, regenerate the format list (also shown in the app):
  `azoth formats --markdown docs/FORMATS.md`. A test fails if it's out of date.
