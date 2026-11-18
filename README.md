# Azoth Converter

An offline desktop file converter for Windows (macOS and Linux later).
**Your files never leave your computer:** no uploads, no cloud, no telemetry. See [PRIVACY.md](PRIVACY.md).

Status: early development (0.1). See the [project plan](docs/PROJECT_PLAN.md) for the roadmap.

## What it converts today

| From | To |
|------|----|
| Word (DOCX, DOC), ODT, RTF, TXT | PDF, other text formats, images |
| **PDF** | **Word (DOCX)**, ODT, RTF, TXT, PNG, JPG, WebP, BMP, TIFF |
| Excel (XLSX, XLS), ODS, CSV | PDF, other spreadsheet formats, images |
| PowerPoint (PPTX, PPT), ODP | PDF, other presentation formats, images |
| JPG, PNG, WebP, HEIC, AVIF, BMP, TIFF, GIF, ICO | each other, and PDF |

**Full list of every format and what it converts into: [docs/FORMATS.md](docs/FORMATS.md).** The app shows the same list under **Supported formats**.

Plus PDF merge and split from the command line.

**Quality first:** conversions aim to be as close to 1:1 as possible. Photos are put into PDFs
unchanged, lossless images stay lossless, and if Microsoft Word is installed it's used for
Word → PDF for an exact layout. Under **Options → Quality** you can choose smaller files
instead, but never below a sensible minimum.

Office formats need [LibreOffice](https://www.libreoffice.org/download/) (free) to be installed.
PDF → Word, PDF ↔ images and the image conversions work without it.

## Using it

**Install:** run `AzothConverter-Setup-<version>.exe`. No admin rights needed; it installs just for you
unless you choose "all users". Uninstall it from *Settings → Apps* like any other program.

**The app:** start **Azoth Converter** from the Start menu, drag files into the window, choose a format,
click **Convert**. It remembers your format, output folder and quality setting.

**The command line:**

```bash
azoth convert report.docx --to pdf
```

```bash
azoth convert contract.pdf --to docx
```

```bash
azoth convert IMG_0001.heic IMG_0002.heic --to jpg -o converted
```

```bash
azoth formats contract.pdf
```

```bash
azoth pdf merge part1.pdf part2.pdf -o complete.pdf
```

## Development

Requires Python 3.11 or newer.

```bash
python -m venv .venv
```

```bash
.venv\Scripts\activate
```

```bash
pip install --require-hashes -r requirements-dev.lock
```

```bash
pip install --no-deps -e .
```

This installs the exact, hash-checked library versions from the lock file.

```bash
pytest
```

```bash
python -m azoth
```

On Linux or macOS, activate the environment with `source .venv/bin/activate` instead.
`python -m azoth` with no arguments opens the window; with arguments it works like `azoth`.

### Sample files

`samples/` has ready-made test files: formatted Word documents, PDFs (including a
scanned one and a password-protected one), Excel, PowerPoint, photos with GPS data,
and deliberately broken files. See [samples/README.md](samples/README.md).

### Building the Windows app

```bash
cd packaging
```

```bash
pyinstaller azoth.spec --noconfirm
```

The result is in `packaging/dist/AzothConverter/`: `AzothConverter.exe` (the app) and `azoth.exe` (command line).
The installer is made from that folder with [Inno Setup](https://jrsoftware.org/isinfo.php):

```bash
iscc /DAppVersion=0.1.0 installer.iss
```

The app icon is drawn by `python packaging/make_icon.py`.
GitHub Actions builds it automatically for `main`. For any other branch (e.g. `dev`), start a build by hand: **Actions** tab → **CI** → **Run workflow** → choose the branch. When the run finishes, download `AzothConverter-Setup` (the installer) from its **Artifacts** section. Builds from `dev` are kept for 7 days, builds from `main` for 30.

### Project layout

```
src/azoth/
  formats.py        known formats, detection by file content
  engine.py         finds conversion routes, runs them safely
  converters/       one plugin per engine (images, pdf, office)
  cli.py            command line
  gui/              PySide6 app
tests/              pytest suite (blocks network access in every test)
packaging/          PyInstaller spec
samples/            test files to try conversions with
docs/               project plan
```

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).
