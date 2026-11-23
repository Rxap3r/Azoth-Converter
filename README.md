# Azoth Converter

An offline desktop file converter for Windows (macOS and Linux later).
**Your files never leave your computer:** no uploads, no cloud, no telemetry. See [PRIVACY.md](PRIVACY.md).

Status: early development (0.1). What changed in each version: [CHANGELOG.md](CHANGELOG.md). See the [project plan](docs/PROJECT_PLAN.md) for the roadmap.

## What it converts today

| From | To |
|------|----|
| Word (DOCX, DOC), ODT, RTF, TXT | PDF, other text formats, images |
| **PDF** | **Word (DOCX)**, ODT, RTF, TXT, PNG, JPG, WebP, BMP, TIFF |
| Excel (XLSX, XLS), ODS, CSV | PDF, other spreadsheet formats, images |
| PowerPoint (PPTX, PPT), ODP | PDF, other presentation formats, images |
| JPG, PNG, WebP, HEIC, AVIF, BMP, TIFF, GIF, ICO | each other, and PDF |
| Scans and photos of text (images, scanned PDFs) | Word (DOCX) and TXT by text recognition (OCR), searchable PDF |

**Full list of every format and what it converts into: [docs/FORMATS.md](docs/FORMATS.md).** The app shows the same list under **Supported formats**.

**PDF tools:** merge PDFs, split them (every page, or ranges like 1-3, 5), and turn, delete or
reorder pages with page previews. Pages are copied as they are, so there's no quality loss and
the original is never changed. **Compress** saves a smaller copy (three levels, from "no quality
loss" to "smallest file"; only pictures get smaller, text stays sharp). **Password** locks a copy
with AES-256 encryption, or removes the password from your own PDF. **Make searchable** reads
the text in scanned pages (OCR) and adds it invisibly, so you can search and copy it; the pages
look exactly the same. In the app under **PDF tools**, or `azoth pdf` on the command line.

**Text recognition (OCR), offline:** scanned PDFs and photos of letters become Word or text
files; photos can also become a searchable PDF. English, German, French and Italian are
included. Recognition runs on your computer; nothing is uploaded.

**Remove photo metadata:** save a copy of your photos without the hidden information
(GPS location, camera, date, author, comments, preview pictures) before you share them. The
picture itself stays exactly the same. Works for JPG, PNG, WebP, GIF, TIFF, HEIC and AVIF:
in the app, choose **Remove metadata only**; right-click a file and choose
**Show metadata…** to see what it contains first.

**Change picture size:** make photos smaller or bigger while converting, or keep the format
and only change the size. Choose a screen size like Full HD or 4K (turned for portrait
photos), a width, a height or a percentage; proportions are always kept, and nothing is
resized unless you choose a size.
In the app under **Picture size** (or the **Change size only** tile); on the command line
`azoth convert *.jpg --to jpg --resize 2000`.

**Enhance with AI:** enlarge small photos with sharp new detail instead of a blurry
enlargement, or keep their size and make them sharper, with less noise and fewer JPEG
blocks. It runs entirely on your computer (the Real-ESRGAN model, 4.5 MB, is part of the
app) and takes a while: roughly 10 seconds per megapixel of the original on a 4-core
processor. The AI *invents* detail, so the result looks real but isn't fully true to the
original: don't use it for documents, evidence or ID photos. Off unless you tick it; choose
how strongly noise is removed (Low keeps fine grain). Command line:
`azoth convert small.jpg --to png --resize 400% --ai`, or `--ai` alone to keep the size.

**Quality first:** conversions aim to be as close to 1:1 as possible. Photos are put into PDFs
unchanged, lossless images stay lossless, and if Microsoft Office is installed, Word, Excel
and PowerPoint do their own files (to PDF and between their formats) for an exact layout. Under **Quality** next to the format tiles you can choose smaller files
instead, but never below a sensible minimum.

Office formats need Microsoft Office (Word, Excel, PowerPoint) or the free
[LibreOffice](https://www.libreoffice.org/download/). Microsoft Office is used where it's
installed; LibreOffice fills the gaps (e.g. PowerPoint files on a PC with only Word) and steps
in if Office fails. PDF → Word, PDF ↔ images and the image conversions need neither.

## Using it

**Download:** the latest installer is on the [Releases page](https://github.com/Rxap3r/Azoth-Converter/releases/latest).

Each release offers two versions of the same app:
- **AzothConverter-Setup-<version>.exe**: the installer (recommended), with Start menu entry and clean uninstall.
- **AzothConverter-portable-<version>.zip**: no installation; unzip anywhere (also a USB
  stick) and run `AzothConverter.exe`. It keeps its settings and temporary files in a `data`
  folder next to itself, so nothing is left on the computer; delete the folder to remove it.

The "Source code" archives that GitHub adds to every release are only needed by developers.

**Install:** run `AzothConverter-Setup-<version>.exe`. No admin rights needed; it installs just for you
unless you choose "all users". Uninstall it from *Settings → Apps* like any other program; the uninstall is clean
and leaves no files, settings or registry entries behind.

**The app:** start **Azoth Converter** from the Start menu, drag files into the window, pick a format
tile on the right and click **Convert**. It remembers your format, output folder and quality setting.
Under **Settings** you can choose a light or dark look, or let it follow Windows.

**The command line:** in the Windows download the command-line program is
`azoth-terminal.exe` (next to `AzothConverter.exe`; type `azoth-terminal` instead of `azoth`
in the examples). Installed from source with pip, the command is `azoth`.

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
azoth clean holiday.jpg IMG_0002.heic -o to-share
```

```bash
azoth clean --show holiday.jpg
```

```bash
azoth formats contract.pdf
```

```bash
azoth pdf merge part1.pdf part2.pdf -o complete.pdf
```

```bash
azoth pdf split contract.pdf --ranges "1-3, 4-"
```

```bash
azoth pdf edit scan.pdf --delete 2 --rotate 1=90
```

```bash
azoth pdf compress big.pdf --level strong
```

```bash
azoth pdf ocr scan.pdf --language deu
```

```bash
azoth pdf password add contract.pdf
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

Download the text recognition language files (37 MB) and the AI enlarging model (10 MB,
stored as 4.5 MB), checked against fixed checksums (the app itself never downloads
anything):

```bash
python packaging/fetch_tessdata.py
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

The result is in `packaging/dist/AzothConverter/`: `AzothConverter.exe` (the app) and `azoth-terminal.exe` (command line).
The installer is made from that folder with [Inno Setup](https://jrsoftware.org/isinfo.php):

```bash
iscc /DAppVersion=0.2.1 installer.iss
```

The app icon is drawn by `python packaging/make_icon.py`.
GitHub Actions builds it automatically for pull requests into `main` and for `main` itself. For any other branch (e.g. `dev`), start a build by hand: **Actions** tab → **Build and test** → **Run workflow** → choose the branch. When the run finishes, download `AzothConverter-Setup` (the installer) from its **Artifacts** section. These test builds are kept for 7 days; released versions stay permanently on the [Releases page](https://github.com/Rxap3r/Azoth-Converter/releases).

### Project layout

```
src/azoth/
  formats.py        known formats, detection by file content
  engine.py         finds conversion routes, runs them safely
  converters/       one plugin per engine (images, pdf, office, ocr)
  ocr.py            text recognition (Tesseract inside PyMuPDF)
  cli.py            command line
  gui/              PySide6 app
tests/              pytest suite (blocks network access in every test)
packaging/          PyInstaller spec
samples/            test files to try conversions with
docs/               project plan
```

## Code signing policy

Releases are built automatically from this repository. They are **not signed yet**; signing
through the SignPath Foundation's free program for open-source projects is planned. See
[CODE_SIGNING.md](CODE_SIGNING.md).

## Security

Found a security or privacy problem? Please report it privately; see [SECURITY.md](SECURITY.md).

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).
