# CLAUDE.md

Guidance for Claude sessions working on this repository. Sections are in order of
priority: do "Start of every session" first, then follow the rules on how to work.

## Start of every session

1. **Update `dev` and work there.** The SessionStart hook `.claude/hooks/sync-dev.sh` does
   this automatically; if it prints a `SYNC-DEV WARNING`, tell the owner right away. Otherwise
   (never on the automatic `claude/...` session branch, or
   an automatic "unpushed commits" check keeps firing after every answer):
   ```bash
   git fetch origin dev && git checkout dev && git pull --ff-only origin dev
   ```
   If the session started on another branch that already has commits not on `dev`, bring
   them over (`git checkout dev && git merge --no-edit <that-branch>`). If the local `dev`
   is an old leftover and `git pull --ff-only` fails, rename it
   (`git branch -m dev dev-old-local`) and `git checkout -b dev origin/dev`.
2. **Use the cost-saver plugin** (owner, Nov 2026). It is installed in the owner's claude.ai
   account (not in this repository), so it loads in every session: load the
   `cost-saver:cost-saver` skill before the first tool call and follow it. If it is not in
   the skill list, tell the owner in one line instead of carrying on silently.
3. **Read "Current status"** at the end of this file.

Session limits: sessions can push branches but **not tags**, which is why releases are
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

- **Always work on `dev`** (see "Start of every session"), even if the session was started on an
  automatically created branch. This instruction is the owner's explicit permission to push to
  `dev`. Don't create or push to session or feature branches.
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

### Time limits (watch these as the project grows)

Every test and build job has a time limit (`timeout-minutes` in `build-and-test.yml` and
`release.yml`): **30 min** for Tests (Linux) and Tests (Windows), **45 min** for the Windows
app / installer build. A job that runs longer is stopped and fails, so a stuck test can't run
for 6 hours. Normal times (Nov 2026): Linux ~1–2 min, Windows tests ~3–5 min, installer
~4–15 min; one Linux run took 20 min because installing LibreOffice was slow. **When adding
many or slow tests, check the run times in the Actions tab; if a job regularly needs more
than about half its limit, raise the limit (ask the owner, it's a workflow change)** rather
than letting good runs fail.

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
  (`%APPDATA%\Azoth Converter`), never in the registry (only the installer writes the
  right-click menu, and removes it); job temp folders start with
  `engine.TEMP_PREFIX`. Anything new the app writes must be removed by `[UninstallDelete]` in
  `packaging/installer.iss` and checked by the "Test installer" step of the automatic build.
- Untrusted input: catch engine errors and raise `ConversionError` with a message a non-technical user understands.

## Before every commit

- Add every user-visible or workflow change to `CHANGELOG.md` under **Unreleased** (short,
  plain sentences; sections Added / Changed / Fixed / Removed / Quality / Privacy and safety /
  Development).
- `pytest` passes and `ruff` is clean.
- New features come with tests.
- Update `docs/PROJECT_PLAN.md` checkboxes and the README's format table when features change.
- When conversions change, regenerate the format list (also shown in the app):
  `azoth formats --markdown docs/FORMATS.md`, and the right-click menu:
  `python packaging/make_context_menu.py`. Tests fail if either is out of date.
## Project

Azoth Converter is an **offline** desktop file converter (Windows first, later macOS and Linux).
The whole point of the project is **data safety**: files never leave the user's device.
The roadmap is in `docs/PROJECT_PLAN.md`, and the user-facing promises are in `PRIVACY.md`.
Future ideas and change requests from the owner go into `docs/PROJECT_PLAN.md` as unchecked items
in the matching phase (design wishes under "Design refresh"); there is no separate wish list.

Stack: Python 3.11+, PySide6 (GUI), Pillow and pillow-heif (images), PyMuPDF and pdf2docx (PDF),
openpyxl (PDF → Excel), FFmpeg (video and audio), LibreOffice headless (office formats),
PyInstaller (Windows build). License: GPL-3.0-or-later.

## Public repository

The repository is public. Never commit secrets, personal data or real user files (samples are
made up). Commits are authored as "Claude <noreply@anthropic.com>"; don't put the owner's
email or other personal details into commits, code or docs. Security reports go through
GitHub's private vulnerability reporting (see `SECURITY.md`), never public issues.

## Commands

```bash
pip install --require-hashes -r requirements-dev.lock
```

```bash
pip install --no-deps -e .
```

```bash
python packaging/fetch_tessdata.py
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

## Layout

```
src/azoth/
  formats.py          format list and detection by file content
  engine.py           route finding (multi-step), running jobs, temp folders
  converters/base.py  Converter plugin interface
  converters/*.py     images, pdf, office (LibreOffice), msword (Microsoft Word, Excel,
                      PowerPoint via PowerShell) plugins; register new ones in converters/__init__.py
  cli.py              `azoth` command line
  pdf_tools.py        merge, split, edit pages, compress, passwords (used by the app and `azoth pdf`)
  ocr.py              text recognition (Tesseract inside PyMuPDF): searchable PDF, page texts;
                      converters/ocr.py = images → TXT/DOCX; language files in
                      resources/tessdata (not in git: `python packaging/fetch_tessdata.py`)
  portable.py         portable mode (portable.txt next to the exe → data/ and data/temp beside it)
  office_password.py  passwords on Word/Excel/PowerPoint files (add, remove, unlock for converting)
  resize.py           picture size (longest side, width, height, fit, %); used by converters/images.py
  upscale.py          "Enhance with AI" (Real-ESRGAN run by OpenCV's dnn, tiled); model in
                      resources/upscale (not in git: fetched by packaging/fetch_tessdata.py)
  converters/media.py video and audio (FFmpeg): copies tracks where possible, removes GPS/phone
                      metadata, keeps song tags; FFmpeg in resources/ffmpeg on Windows (not in
                      git: fetched by packaging/fetch_ffmpeg.py, called by fetch_tessdata.py)
  converters/pdf_excel.py  PDF → Excel (tables found by PyMuPDF, written by openpyxl)
  media_metadata.py   show/remove metadata of videos and music (FFmpeg copies the tracks,
                      every packet compared before saving)
  metadata.py         show/remove metadata (`azoth clean`); photos: byte-level code in converters/strip.py;
                      PDF/DOCX/XLSX/PPTX: doc_metadata.py
  context_menu.py     Explorer right-click menu entries → packaging/context_menu.iss
                      (`python packaging/make_context_menu.py`; gui/explorer.py hands files to one window)
  gui/                PySide6 app (design "A"): main_window.py = sidebar + pages, runs jobs;
                      convert_page.py (layout), file_list.py (file cards), target_picker.py
                      (format tiles), options_panel.py (quality), output_folder.py,
                      formats_panel.py, settings_page.py, done_card.py ("Done" card +
                      Windows notification), pdf_tools_page.py (Merge / Split /
                      Edit pages / Compress / OCR; also the Password page), worker.py (background thread),
                      targets.py (which targets are offered, no Qt), theme.py (light/dark
                      colours + stylesheet; widgets only set a "role" property), icons.py
                      (line icons drawn from SVG), About dialog, settings.py (QSettings)
                      error_log.py (local error log + crash dump, Settings → Error log…)
  resources/          icon.png (drawn by packaging/make_icon.py)
tests/                pytest; conftest.py blocks all network access in every test
packaging/            PyInstaller spec (AzothConverter.exe + azoth-terminal.exe), installer.iss (Inno Setup),
                      make_icon.py; the automatic build creates and tests the installer
.github/workflows/    only two workflows: build-and-test.yml and release.yml (shown in the Actions tab)
.github/actions/      their shared steps: run-tests, build-windows (composite actions, not listed)
samples/              test files (Word, PDF, Excel, PowerPoint, images, problem files);
                      recreate with `python samples/generate.py`, see samples/README.md
```

To add a format family, write a new `Converter` subclass with `capabilities()` and `convert()`,
register it, and add tests. The engine, CLI and GUI pick it up automatically.

## Look and feel

**Keep it calm (owner, 23 Nov 2026):** short labels; explanations go into tooltips (hover),
not into text under the control. Only warnings the user must see stay visible (e.g. the
AI's "not for documents or ID photos"). Rarely changed choices go under "More options" on
the Convert page. Show an option only where it changes something.

Never call `setVisible(True)`/`show()` on a widget before it has a parent, and never remove
one with `setParent(None)`: on Windows it flashes up as a small window of its own. Hide
instead (`if not x: w.hide()`) and remove with `widgets.discard()`.

Pages and panels whose content can grow are wrapped in `widgets.scrollable()`, so a low window
(or larger Windows text) scrolls instead of squeezing buttons on top of each other;
`test_no_page_squeezes_its_buttons` checks every page.

All colours are in `gui/theme.py` (one set for light, one for dark); widgets never hard-code
colours, they set a `role` property that the stylesheet styles. `tests/test_theme.py` checks
every colour pair for readable contrast: keep it passing when colours change.

## Writing messages

Error messages and warnings use the style of **Simplified Technical English** (ASD-STE100,
owner's choice, Nov 2026): short sentences, one statement each; active voice ("Azoth
Converter did not save a file", not "Nothing was saved"); instructions start with the verb
("Enter …", "Select …", "Remove …"); no contractions, no "please", "Cannot …" instead of
"Could not …", "possibly" instead of "may be", "install … again" instead of "reinstall".
Technical details from an engine go in brackets at the end: "Cannot read the PDF (…)."
This covers error messages, tooltips, notes (`quality_note`, `*_NOTE`) and command-line
help; button labels stay short as they are.

Words come from the STE100 Issue 9 dictionary (checked Nov 2026 with an unofficial copy
of its word list; the official standard is free from asd-ste100.org after a request
form). Common fixes: need → necessary, may → can / possibly, every → each, big → large,
already / instead → rephrase, fail → cannot …, work (verb) → rephrase, real → correct,
original → initial. Allowed as technical words: computer verbs (save, delete, copy,
convert, search, upload …) and names of things (PDF, password, track, scan, the app's
"Picture size" function). `tests/test_messages.py` checks all these texts for short
forms, "please" and the most common rejected words.

## Languages

The app and the installer always offer the same languages (currently English only). When adding
a translation to the app, add the matching Inno Setup language to `packaging/installer.iss` in the
same change, and never add an installer language the app doesn't have.

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

## Current status (keep this section up to date)

Details are in `CHANGELOG.md` (what each version contains) and `docs/PROJECT_PLAN.md`
(open ideas). Keep only what a new session needs here; move finished details out.

- **Released:** **0.6.0** (24 Nov 2026, pull request #12) on GitHub Releases (installer +
  portable ZIP). Earlier: 0.5.0 (23 Nov), 0.4.0, 0.3.1, 0.3.0 (22 Nov), 0.2.1 (21 Nov),
  0.2.0 (19 Nov), 0.1.0 (18 Nov). New work goes under `CHANGELOG.md` → Unreleased.
- **Repository:** public at `Rxap3r/Azoth-Converter` (renamed from `File-Converter`; the old
  URL redirects, but connect new sessions to the new name). A ruleset protects **only
  `main`** (pull request required, checks Tests (Linux), Tests (Windows) and Windows app
  required); `dev` accepts direct pushes. Dependabot alerts, private vulnerability reporting
  and two-factor authentication are on.
- **Next (candidates for 0.7.0, owner to choose):** PDF redaction (owner has something
  to add first); German translation; smaller download; code signing (waiting for
  SignPath). The **design refresh is low priority** (the owner finds the current design
  good): icon rework, "Done" notification, accessibility checks. Later: version check
  inside the app (only on click, after code signing), OCR speed on long PDFs. All in `docs/PROJECT_PLAN.md`.
- **On `dev` for 0.7.0:** "Best quality (slow)" AI (`--ai-best`, bigger model, +30 MB
  download); the Windows build smoke-tests both AI models in the finished program.
  "Make smaller" for videos (`--shrink`, option `shrink`, tile `SHRINK_TARGET`), also in
  the right-click menu. PDF → Excel "Tables only" / "All pages on one sheet" (options
  `tables_only`, `one_sheet`; `gui/options_panel.ExcelOptions`). Code review fixes.
- **Still to try on a real Windows PC** (owner's company PC has Office, no LibreOffice): AI
  on real photos; Excel/PowerPoint → PDF, XLS → XLSX, PPT → PPTX; Office passwords both
  ways; the right-click menu; the double-clicked `azoth-terminal.exe` Command Prompt; videos
  from a phone; PDF → Excel on real bills/statements; metadata removal on real phone photos;
  style A (Light / Dark / Follow Windows).
- **Open:** a crash the owner saw in 0.2.0 (several photos, some already PNG, then Convert)
  couldn't be reproduced; probably the "access violation" fixed by `gui/main_thread_gc.py`
  (Python's garbage collection in a conversion thread freeing Qt objects).
- **Code signing is postponed** (owner, Nov 2026): first make the app good, then sign.
  Releases are **not signed**; `CODE_SIGNING.md`, the README and the release notes say so
  (keep them honest until signing really works). Steps:
  1. ✓ `CODE_SIGNING.md` is on `main` (pull request #5);
  2. the owner applies on signpath.org (worried a small project may be declined). **Wait for
     SignPath's answer** before planning more; alternatives if declined: Certum open-source
     certificate, Azure Trusted Signing;
  3. after approval, the owner saves the SignPath API key as a GitHub secret (never in chat);
  4. then add signing to `.github/workflows/release.yml` / `.github/actions/build-windows`:
     build → sign the `.exe` files → build the installer → sign the installer, with manual
     approval per release in SignPath.
- **Settled, don't reopen:** OCR text selection is fine in Chrome/Edge and good enough in
  Firefox (owner: don't tune further).
- **Test note:** GUI tests use `MainThreadGC` in the `window` fixture like the app (a
  Windows test crashed without it while the AI ran in the worker thread).
