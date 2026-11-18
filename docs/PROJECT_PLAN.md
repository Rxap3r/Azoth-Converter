# File-Converter: Project Plan

A desktop file converter that runs **entirely offline** on the user's device.
No uploads, no cloud, no telemetry. Windows first, then macOS and Linux.

---

## 1. Goals and principles

| # | Principle | What it means in practice |
|---|-----------|---------------------------|
| 1 | **Local only** | No conversion step ever opens a network connection. Every engine is bundled with the app. |
| 2 | **No telemetry** | No analytics, crash reporting or "phone home". Update checks are off by default and only run when the user clicks "Check for updates". |
| 3 | **Leave no traces** | Temporary files go to a private per-job folder that is deleted when the job finishes, including when it fails or is cancelled. |
| 4 | **Safe with untrusted files** | Converter engines run as separate processes with hardened settings: macros off, external links off, network protocols off. |
| 5 | **Transparent** | Open source, bundled components listed in an SBOM, signed releases, readable privacy statement. |
| 6 | **Simple for everyone** | Drag files in, pick a target format, click Convert. Advanced options stay hidden until you open them. |

**Non-goals for now:** cloud sync, user accounts, a web version, mobile apps.

---

## 2. Technology choice

### Recommended stack

| Layer | Choice | Why |
|-------|--------|-----|
| Language | **Python 3.12+** | Best ecosystem of conversion libraries. Runs on all three desktop systems, which keeps the later macOS and Linux versions cheap. |
| GUI | **PySide6 (Qt 6)** | Native-looking, mature, LGPL license, handles drag-and-drop, dark mode and high-DPI screens well. |
| Packaging | **PyInstaller** (or Nuitka), then **Inno Setup**, with MSIX/winget later | Produces a normal Windows installer plus a portable ZIP version. |
| Engines | Proven external tools wrapped behind one interface (see §4) | Don't reinvent codecs. FFmpeg, LibreOffice and similar tools are the industry standard. |
| CI | GitHub Actions on `windows-latest` | Builds, tests and packages on every push. |

### Alternatives considered

- **C# / .NET (WinUI 3 or WPF):** the most native Windows result, but macOS and Linux later would mean a rewrite or switching to Avalonia. Fewer conversion libraries.
- **Tauri (Rust and a web frontend):** small installer and a modern UI, but a steeper learning curve, and most conversion work would still call the same external tools.
- **Electron:** large memory footprint and it ships a whole browser. That's poor value for a privacy tool.

---

## 3. Architecture

```
┌───────────────────────────────────────────────────────────┐
│  GUI (PySide6)            CLI (fileconv …)                │
│  drag & drop, queue,      same features, scriptable       │
│  presets, settings                                        │
└──────────────┬───────────────────────┬────────────────────┘
               │                       │
┌──────────────▼───────────────────────▼────────────────────┐
│  Core                                                     │
│  • Format detection (magic bytes, not just extension)     │
│  • Conversion graph: finds a route A → B, possibly via    │
│    an intermediate (e.g. DOCX → PDF → PNG)                │
│  • Job queue: parallel workers, progress, cancel          │
│  • Temp-file manager: private per-job dir, always cleaned │
│  • Settings and presets (local JSON in %APPDATA%)         │
└──────────────┬────────────────────────────────────────────┘
               │  Converter plugin interface
┌──────────────▼────────────────────────────────────────────┐
│  Converter plugins (one per engine)                       │
│  ImageConverter · MediaConverter (FFmpeg) ·               │
│  OfficeConverter (LibreOffice) · PdfConverter ·           │
│  DataConverter · ArchiveConverter · EbookConverter · OCR  │
└──────────────┬────────────────────────────────────────────┘
               │  subprocess / library calls, sandboxed
┌──────────────▼────────────────────────────────────────────┐
│  Bundled engines (shipped inside the install folder)      │
└───────────────────────────────────────────────────────────┘
```

**Plugin contract (sketch):**

```python
class Converter(Protocol):
    id: str
    def capabilities(self) -> list[tuple[Format, Format]]: ...
    def options_schema(self, src: Format, dst: Format) -> OptionsSchema: ...
    def convert(self, job: Job, progress: ProgressCallback,
                cancel: CancelToken) -> Result: ...
```

Adding a new format family means adding one plugin, with no changes to the GUI
or core. The GUI builds its options panel from `options_schema`.

**Suggested repository layout:**

```
src/fileconv/
  core/          # detection, graph, queue, tempfiles, settings
  converters/    # one module per plugin
  gui/           # PySide6 windows and widgets
  cli/           # command-line entry point
tests/
  fixtures/      # small sample files per format
  ...
packaging/       # PyInstaller spec, Inno Setup script, engine fetch scripts
docs/
```

---

## 4. Format coverage and engines

| Category | Formats | Engine | License note |
|----------|---------|--------|--------------|
| Images | JPG, PNG, WebP, BMP, TIFF, GIF, ICO, HEIC/HEIF, AVIF | Pillow, pillow-heif, pillow-avif | Permissive |
| Vector images | SVG → PNG/PDF | resvg | Permissive |
| Camera RAW | CR2, NEF, ARW, DNG → JPG/TIFF | rawpy (LibRaw) | LGPL |
| Audio | MP3, WAV, FLAC, AAC/M4A, OGG, OPUS, WMA (read) | FFmpeg | LGPL build recommended |
| Video | MP4, MKV, MOV, AVI, WebM, WMV (read), GIF output | FFmpeg | LGPL build; H.264/H.265 encoding needs a GPL build (see §8) |
| Office docs | DOCX, DOC, ODT, RTF, TXT → PDF and between each other | LibreOffice (headless) | MPL 2.0 |
| Spreadsheets | XLSX, XLS, ODS, CSV | LibreOffice, openpyxl | MPL / MIT |
| Presentations | PPTX, PPT, ODP → PDF / images | LibreOffice | MPL 2.0 |
| Markup | Markdown, HTML, DOCX, ODT, EPUB | Pandoc | GPL (run as a separate program) |
| PDF tools | merge, split, rotate, compress, PDF ↔ images, PDF → text | pypdf, pikepdf, pypdfium2 | Permissive (avoid AGPL PyMuPDF and Ghostscript unless the project is open source) |
| Data | CSV, TSV, JSON, XML, YAML, XLSX, Parquet | pandas, pyarrow | Permissive |
| Archives | ZIP, 7Z, TAR, GZ, (RAR extract only) | py7zr, built-in zipfile and tarfile, 7-Zip | LGPL; unRAR license allows extracting only |
| E-books | EPUB, MOBI/AZW3, FB2 | Pandoc (EPUB), Calibre `ebook-convert` (optional) | GPL (run as a separate program) |
| OCR | Scanned PDF/image → searchable PDF / text | Tesseract and OCRmyPDF | Apache / MPL |

---

## 5. Roadmap

Time estimates assume one developer working part-time. Treat them as rough guides, not deadlines.

### Phase 0: Foundations (≈ 2 weeks)
- [ ] Repository structure, `pyproject.toml`, linting (ruff), type checking (mypy), pytest
- [ ] Core: format detection, plugin interface, job queue, temp-file manager
- [ ] CLI skeleton: `fileconv input.png --to webp`
- [ ] GitHub Actions: tests on Windows and a PyInstaller build artifact
- [ ] `PRIVACY.md`: the promises from §1, written in plain language

**Exit criteria:** one dummy conversion runs end-to-end through the CLI on a CI Windows machine.

### Phase 1: MVP with images and PDF (≈ 4–6 weeks)
- [ ] Image plugin: all image formats in §4 except RAW and SVG
- [ ] Options: quality, resize, keep or strip metadata (EXIF/GPS **stripped by default**)
- [ ] PDF plugin: images → PDF, PDF → images, merge, split, rotate
- [ ] GUI v1: drag-and-drop area, file list, target format picker, output folder, progress, cancel, "open folder" when done
- [ ] Batch conversion (multiple files at once, parallel workers)
- [ ] Windows installer and portable ZIP
- [ ] **Release 0.1** (internal or beta testers)

**Exit criteria:** a non-technical tester converts 50 mixed photos (including iPhone HEIC files) to JPG without help.

### Phase 2: Audio and video (≈ 4 weeks)
- [ ] FFmpeg plugin with progress parsed from FFmpeg's output
- [ ] Presets: "MP4 for sharing", "MP3 320k", "Extract audio", "Make GIF", "Shrink video"
- [ ] Trim (start and end time), resolution, bitrate, mute
- [ ] Hardening: `-protocol_whitelist file` so FFmpeg can't reach the network through a malicious playlist file
- [ ] **Release 0.2**

### Phase 3: Office documents and data (≈ 4–6 weeks)
- [ ] LibreOffice headless plugin: Word, Excel and PowerPoint formats → PDF and between each other
- [ ] Hardening: macros disabled, external link updates disabled, a fresh throwaway LibreOffice profile per job
- [ ] Data plugin: CSV ↔ XLSX ↔ JSON ↔ XML ↔ YAML, with encoding and delimiter detection
- [ ] Pandoc plugin: Markdown ↔ HTML ↔ DOCX ↔ EPUB
- [ ] Decide how to ship LibreOffice (§8, size risk)
- [ ] **Release 0.3, public beta**

### Phase 4: Power features (≈ 6–8 weeks, pick by demand)
- [ ] Windows Explorer right-click menu: "Convert with File-Converter → …"
- [ ] Watch folders (files dropped in a folder are converted automatically)
- [ ] OCR: scanned PDF → searchable PDF (Tesseract, with bundled German, English, French and Italian language packs)
- [ ] PDF compress, password-protect or remove password (only with the user's own password), redaction
- [ ] Archives, e-books, Camera RAW, SVG
- [ ] Saved presets, conversion history (stored locally, can be cleared, can be turned off)
- [ ] Hardware video encoding (NVENC, Quick Sync, AMF) when the GPU supports it

### Phase 5: Production release (≈ 3–4 weeks)
- [ ] Code-signing certificate so Windows SmartScreen doesn't warn users
- [ ] SBOM (CycloneDX) and third-party license notices bundled in the app
- [ ] Accessibility: keyboard navigation, screen reader labels, high-contrast mode
- [ ] Translations (Qt Linguist), for example English, German and French first
- [ ] Publish on winget and optionally the Microsoft Store (MSIX)
- [ ] **Release 1.0**

### Phase 6: Other platforms
- [ ] macOS (.dmg, notarized, Apple Silicon and Intel)
- [ ] Linux (AppImage and/or Flatpak)

---

## 6. Data-safety checklist

These checks run in CI and must pass before every release.

| Check | How |
|-------|-----|
| No network during conversion | Integration tests run with network access blocked (Windows Firewall rule in CI) and fail if any process opens a socket |
| No telemetry dependencies | A dependency audit fails the build if a package with known analytics or reporting behaviour is added |
| Temp files cleaned | Tests check that the temp directory is empty after success, failure and cancel |
| Metadata stripping works | Tests check that GPS and EXIF data is gone when the "strip" option is on |
| Engines hardened | ImageMagick (if used) runs with a restrictive `policy.xml`; FFmpeg with `protocol_whitelist`; LibreOffice with macros and links off |
| Untrusted input | Fuzz tests on the format detection and parsers; malformed sample files in `tests/fixtures/malicious/` |
| Supply chain | Locked dependency versions with hashes, engine downloads checked against SHA-256 values at build time, signed release binaries |
| Originals untouched | Originals are never overwritten. Output always goes to a new file and existing files are never silently replaced |

---

## 7. Testing strategy

- **Unit tests:** core logic (route-finding, detection, option validation).
- **Golden-file tests:** convert sample files and check the output by format, size, page count and duration, and visual similarity for images.
- **Round-trip tests:** e.g. PNG → WebP → PNG keeps the dimensions; CSV → XLSX → CSV keeps the data.
- **GUI smoke tests:** pytest-qt drives the main window.
- **Manual release checklist:** a clean Windows 10 and Windows 11 VM: install, convert one file per category, uninstall, check nothing is left behind.

---

## 8. Risks and open decisions

| Risk / decision | Impact | Proposed answer |
|-----------------|--------|-----------------|
| **Installer size.** LibreOffice adds about 350 MB, FFmpeg about 100 MB | Large download | Ship a "Core" installer (images, PDF, media, data) plus an optional **offline "Office pack"** installer. Also detect and use an existing LibreOffice installation. No downloading on the user's behalf. |
| **Licensing.** GPL/AGPL components (FFmpeg GPL build, Ghostscript, PyMuPDF, Calibre) | Restricts closed-source or commercial distribution | Decide early: **open source (GPL-3.0)** allows everything. If closed or commercial, use only LGPL/permissive engines and run GPL tools as separate optional programs. |
| **H.264/H.265 patents and encoders** | The LGPL FFmpeg build has no x264 or x265 encoders | Use the Windows Media Foundation or GPU hardware encoders through FFmpeg, or adopt GPL. |
| **Malicious input files** | A crafted file could exploit an engine | Separate processes, hardened flags, time and memory limits per job, engines kept up to date. |
| **SmartScreen warnings** | Users get scared off before installing | Budget for a code-signing certificate before the public beta. |
| **Formats that can't convert perfectly** (e.g. complex DOCX → ODT) | User disappointment | Show a "quality warning" for routes that lose information. |

---

## 9. Immediate next steps

1. Decide **licence model** (open source vs. closed/commercial). This changes which engines are allowed.
2. Confirm **stack** (Python and PySide6 recommended).
3. Start Phase 0: project skeleton, core interfaces, CI build on Windows.
4. Gather a set of real-world sample files (HEIC photos, phone videos, office docs) for tests.
