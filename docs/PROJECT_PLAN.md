# File-Converter: Project Plan

A desktop file converter that runs **entirely offline** on the user's device.
No uploads, no cloud, no telemetry. Windows first, then macOS and Linux.

---

## 0. Decisions made

| Topic | Decision |
|-------|----------|
| License | **Open source, GPL-3.0-or-later.** The repository stays private until basic use is solid, then goes public. Because the project is GPL, we can use GPL and AGPL engines (PyMuPDF, Ghostscript, a full FFmpeg build). PyMuPDF is AGPL-3.0; section 13 of the GPL-3.0 and the AGPL-3.0 explicitly allows combining the two. |
| Priorities | **PDF conversions first**, especially **Word → PDF** and **PDF → Word**, then the other office formats. |
| Stack | Python 3.12 and PySide6 (Qt 6), packaged with PyInstaller (see §2). |
| Office engine | LibreOffice (headless). For now the app uses an installed LibreOffice. A bundled "Office pack" comes later. |

---

## 1. Goals and principles

| # | Principle | What it means in practice |
|---|-----------|---------------------------|
| 1 | **Local only** | No conversion step ever opens a network connection. Every engine runs on the device. |
| 2 | **No telemetry** | No analytics, crash reporting or "phone home". Update checks are off by default and only run when the user clicks "Check for updates". |
| 3 | **Leave no traces** | Temporary files go to a private per-job folder that is deleted when the job finishes, including when it fails or is cancelled. |
| 4 | **Safe with untrusted files** | Engines run as separate processes with hardened settings: macros off, external links off, network protocols off. |
| 5 | **Never destroy data** | Originals are never modified. Existing files are never overwritten unless the user asks. |
| 6 | **Transparent** | Open source, bundled components listed in an SBOM, signed releases, a readable [privacy statement](../PRIVACY.md). |
| 7 | **Simple for everyone** | Drag files in, pick a target format, click Convert. Advanced options stay hidden until you open them. |

**Non-goals for now:** cloud sync, user accounts, a web version, mobile apps.

---

## 2. Technology

| Layer | Choice | Why |
|-------|--------|-----|
| Language | **Python 3.12+** | Best ecosystem of conversion libraries. Runs on all three desktop systems, which keeps the later macOS and Linux versions cheap. |
| GUI | **PySide6 (Qt 6)** | Native-looking, mature, handles drag-and-drop, dark mode and high-DPI screens. |
| Packaging | **PyInstaller**, then an **Inno Setup** installer and a portable ZIP, with winget/MSIX later | A normal Windows install experience. |
| Engines | Proven tools wrapped behind one plugin interface (see §4) | FFmpeg, LibreOffice and PyMuPDF are industry standard. No need to reinvent codecs. |
| CI | GitHub Actions on Windows and Linux | Tests, lint and the Windows build on every push. |

---

## 3. Architecture

```
┌───────────────────────────────────────────────────────────┐
│  GUI (PySide6)            CLI (fileconv …)                │
│  drag & drop, queue,      same features, scriptable       │
│  options                                                  │
└──────────────┬───────────────────────┬────────────────────┘
               │                       │
┌──────────────▼───────────────────────▼────────────────────┐
│  Engine (src/fileconv/engine.py)                          │
│  • Format detection by content (formats.py)               │
│  • Route finding: A → B, possibly via an intermediate     │
│    (e.g. DOCX → PDF → PNG), up to 3 steps                 │
│  • Private temp folder per job, always cleaned            │
│  • Never overwrites; progress and cancel                  │
└──────────────┬────────────────────────────────────────────┘
               │  Converter plugin interface (converters/base.py)
┌──────────────▼────────────────────────────────────────────┐
│  ImageConverter (Pillow) · PdfToWord (pdf2docx) ·         │
│  PdfToImage / PdfToText (PyMuPDF) · Office (LibreOffice)  │
│  … later: Media (FFmpeg), OCR, Data, Archives, E-books    │
└───────────────────────────────────────────────────────────┘
```

A new format family means one new plugin: declare `capabilities()` and
implement `convert()`. The engine and GUI pick it up automatically.

---

## 4. Format coverage and engines

✅ = working now, 🔜 = planned

| Category | Formats | Engine | Status |
|----------|---------|--------|--------|
| **Word ↔ PDF** | DOCX, DOC, ODT, RTF, TXT → PDF | LibreOffice | ✅ |
| **PDF → Word** | PDF → DOCX (also DOC, ODT, RTF via DOCX) | pdf2docx | ✅ |
| **PDF → images / text** | PDF → PNG, JPG, WebP, BMP, multi-page TIFF; PDF → TXT | PyMuPDF | ✅ |
| **Images → PDF** | any image → PDF | Pillow | ✅ |
| PDF tools | merge, split | PyMuPDF | ✅ (command line) |
| PDF tools | rotate, reorder, compress, password, in the GUI | PyMuPDF | 🔜 |
| Scanned PDFs | OCR → searchable PDF, then Word | Tesseract | 🔜 |
| Spreadsheets | XLSX, XLS, ODS, CSV ↔ each other, → PDF | LibreOffice | ✅ |
| Presentations | PPTX, PPT, ODP ↔ each other, → PDF, → images | LibreOffice | ✅ |
| Images | JPG, PNG, WebP, BMP, TIFF, GIF, ICO, HEIC, AVIF | Pillow, pillow-heif | ✅ |
| Camera RAW, SVG | CR2, NEF, ARW, DNG, SVG | rawpy, resvg | 🔜 |
| Audio | MP3, WAV, FLAC, AAC/M4A, OGG, OPUS | FFmpeg | 🔜 |
| Video | MP4, MKV, MOV, AVI, WebM, GIF | FFmpeg | 🔜 |
| Markup / e-books | Markdown, HTML, EPUB, MOBI | Pandoc, Calibre | 🔜 |
| Data | CSV, JSON, XML, YAML, XLSX | pandas | 🔜 |
| Archives | ZIP, 7Z, TAR, (RAR extract) | py7zr, 7-Zip | 🔜 |

---

## 5. Roadmap

Time estimates assume one developer working part-time. Treat them as rough guides, not deadlines.

### Phase 0: Foundations ✅ done
- [x] Repository structure, `pyproject.toml`, ruff, pytest
- [x] Engine: content-based format detection, plugin interface, route finding, temp-file handling
- [x] CLI: `fileconv convert`, `fileconv formats`, `fileconv pdf merge/split`
- [x] GitHub Actions: tests on Windows and Linux, plus a Windows build artifact
- [x] `PRIVACY.md`, and a test fixture that fails any test that touches the network

### Phase 1: PDF and Office MVP (mostly done, then release 0.1 and go public)
- [x] Word/Excel/PowerPoint/OpenDocument → PDF and between each other (LibreOffice, hardened profile per job)
- [x] PDF → Word (pdf2docx), with a clear message for scanned PDFs
- [x] PDF → images (one file per page, or multi-page TIFF), PDF → text, images → PDF
- [x] Image conversions with metadata removal by default (GPS/EXIF)
- [x] GUI v1: drag and drop, batch list, target picker, output folder, options, progress, cancel
- [ ] Test with real-world files: complex Word layouts, large PDFs, Excel with several sheets
- [ ] **Optional Microsoft Word engine:** if Word is installed, use it for Word → PDF, which gives exact layout fidelity
- [ ] Remember settings between sessions (last format, output folder), stored locally only
- [ ] Inno Setup installer (Start menu entry, file associations optional, clean uninstall)
- [ ] App icon, About dialog with licenses
- [ ] **Release 0.1**, then make the repository public

### Phase 2: PDF power tools and OCR (≈ 4–6 weeks)
- [ ] PDF tools in the GUI: merge (with drag-to-reorder), split by range, rotate, delete or reorder pages, page thumbnails
- [ ] Compress PDF (downsample images)
- [ ] Add or remove a password (only with the user's own password)
- [ ] OCR: scanned PDF or photo → searchable PDF, then → Word (bundled Tesseract with German, English, French and Italian language packs)
- [ ] PDF → Excel for tables
- [ ] **Release 0.2**

### Phase 3: Audio and video (≈ 4 weeks)
- [ ] FFmpeg plugin with progress parsed from FFmpeg's output
- [ ] Presets: "MP4 for sharing", "MP3 320k", "Extract audio", "Make GIF", "Shrink video"
- [ ] Trim, resolution, bitrate, mute; hardware encoding (NVENC, Quick Sync, AMF)
- [ ] Hardening: `-protocol_whitelist file` so FFmpeg can't reach the network through a malicious playlist file
- [ ] **Release 0.3**

### Phase 4: More formats and convenience (≈ 6–8 weeks, pick by demand)
- [ ] Windows Explorer right-click menu: "Convert with File-Converter → …"
- [ ] Watch folders (files dropped in a folder are converted automatically)
- [ ] Data formats (CSV/JSON/XML/YAML/XLSX), Markdown/HTML/EPUB, archives, Camera RAW, SVG
- [ ] Saved presets, optional local conversion history (can be cleared or turned off)

### Phase 5: Production release 1.0 (≈ 3–4 weeks)
- [ ] **Bundled "Office pack"** so users don't need to install LibreOffice separately (offline installer)
- [ ] Smaller download: trim unused Qt and OpenCV parts, or try Nuitka
- [ ] Code-signing certificate so Windows SmartScreen doesn't warn users
- [ ] SBOM (CycloneDX) and third-party license notices bundled in the app
- [ ] Accessibility (keyboard navigation, screen readers, high contrast), translations
- [ ] Publish on winget and optionally the Microsoft Store (MSIX)

### Phase 6: Other platforms
- [ ] macOS (.dmg, notarized, Apple Silicon and Intel)
- [ ] Linux (AppImage and/or Flatpak)

---

## 6. Data-safety checklist

| Check | How | Status |
|-------|-----|--------|
| No network in the app process | Autouse pytest fixture blocks sockets for every test | ✅ |
| No network from engines (LibreOffice, later FFmpeg) | CI job with network blocked at the OS level (firewall rule) | 🔜 |
| Temp files cleaned | Tests check the temp folder after success, failure and cancel | ✅ |
| Metadata stripping | Tests check that GPS and EXIF data is gone, and that rotation is still correct | ✅ |
| LibreOffice hardened | Fresh profile per job: macros disabled, link updates never, update check off | ✅ |
| Originals untouched, no silent overwrite | Tests | ✅ |
| Untrusted input | Fuzz tests on detection and parsers; malicious sample files | 🔜 |
| Supply chain | Locked dependency versions with hashes, signed releases, SBOM | 🔜 |

---

## 7. Testing strategy

- **Unit and integration tests** (`tests/`): every converter, the engine, the CLI and the GUI (pytest-qt, headless).
- **Round-trip tests:** e.g. DOCX → PDF → DOCX keeps headings, text and tables.
- **Office tests** run when LibreOffice is installed. CI installs it on both Windows and Linux.
- **Manual release checklist:** a clean Windows 10 and Windows 11 VM: install, convert one file per category, uninstall, check nothing is left behind.

---

## 8. Risks

| Risk | Impact | Plan |
|------|--------|------|
| **Download size.** pdf2docx needs OpenCV (~170 MB) and Qt adds ~100 MB; LibreOffice would add ~350 MB more | Large download | Phase 5: trim the bundle, keep the Office pack as a separate optional offline installer, and keep using an existing LibreOffice when one is installed. |
| **PDF → Word quality.** A PDF has no "paragraphs"; the layout has to be guessed | Complex layouts need touching up | Show the quality note in the app; test against real documents; OCR for scans (Phase 2). |
| **Word → PDF fidelity with LibreOffice.** Fonts or complex layouts may differ slightly from Word | Small layout shifts | Use the installed Microsoft Word when available (Phase 1). Bundle common free fonts. |
| **Malicious input files** | A crafted file could exploit an engine | Separate processes, hardened settings, timeouts, engines kept up to date. |
| **SmartScreen warnings** | Users get scared off before installing | Code-signing certificate before 1.0. Open-source projects can get one free through SignPath. |
