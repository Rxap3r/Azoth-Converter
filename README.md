# File-Converter

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

Office formats need [LibreOffice](https://www.libreoffice.org/download/) (free) to be installed.
PDF → Word, PDF ↔ images and the image conversions work without it.

## Using it

**The app:** start `FileConverter.exe`, drag files into the window, choose a format, click **Convert**.

**The command line:**

```bash
fileconv convert report.docx --to pdf
```

```bash
fileconv convert contract.pdf --to docx
```

```bash
fileconv convert IMG_0001.heic IMG_0002.heic --to jpg -o converted
```

```bash
fileconv formats contract.pdf
```

```bash
fileconv pdf merge part1.pdf part2.pdf -o complete.pdf
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
pip install -e ".[dev]"
```

```bash
pytest
```

```bash
python -m fileconv
```

On Linux or macOS, activate the environment with `source .venv/bin/activate` instead.
`python -m fileconv` with no arguments opens the window; with arguments it works like `fileconv`.

### Sample files

`samples/` has ready-made test files: formatted Word documents, PDFs (including a
scanned one and a password-protected one), Excel, PowerPoint, photos with GPS data,
and deliberately broken files. See [samples/README.md](samples/README.md).

### Building the Windows app

```bash
cd packaging
```

```bash
pyinstaller fileconv.spec --noconfirm
```

The result is in `packaging/dist/FileConverter/`: `FileConverter.exe` (the app) and `fileconv.exe` (command line).
GitHub Actions builds it automatically for `main`. For any other branch (e.g. `dev`), start a build by hand: **Actions** tab → **CI** → **Run workflow** → choose the branch. When the run finishes, download `FileConverter-windows` from its **Artifacts** section. Builds from `dev` are kept for 7 days, builds from `main` for 30.

### Project layout

```
src/fileconv/
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
