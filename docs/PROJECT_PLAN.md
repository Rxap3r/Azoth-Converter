# Azoth Converter: Project Plan

A desktop file converter that runs **entirely offline** on the user's device.
No uploads, no cloud, no telemetry. Windows first, then macOS and Linux.

---

## 0. Decisions made

| Topic | Decision |
|-------|----------|
| Name | **Azoth Converter** (from *azoth*, the alchemists' universal solvent that transforms any substance). Checked Nov 2026: no software trademark "AZOTH" found in the US/EU registers; Swissreg/TMview check by the owner: clear (Nov 2026). CLI command: `azoth`. |
| License | **Open source, GPL-3.0-or-later.** The repository is public since 19 Nov 2026 (after release 0.1.0). Because the project is GPL, we can use GPL and AGPL engines (PyMuPDF, Ghostscript, a full FFmpeg build). PyMuPDF is AGPL-3.0; section 13 of the GPL-3.0 and the AGPL-3.0 explicitly allows combining the two. |
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
| 5 | **1:1 quality** | Conversions as faithful as possible: the best engine available, no needless re-compression, lossless where the target allows. Unavoidable losses are explained in the app. |
| 6 | **Never destroy data** | Originals are never modified. Existing files are never overwritten unless the user asks. |
| 7 | **Transparent** | Open source, bundled components listed in an SBOM, signed releases, a readable [privacy statement](../PRIVACY.md). |
| 8 | **Simple for everyone** | Drag files in, pick a target format, click Convert. Advanced options stay hidden until you open them. |

**Non-goals for now:** cloud sync, user accounts, a web version, mobile apps.

---

## 2. Technology

| Layer | Choice | Why |
|-------|--------|-----|
| Language | **Python 3.12+** | Best ecosystem of conversion libraries. Runs on all three desktop systems, which keeps the later macOS and Linux versions cheap. |
| GUI | **PySide6 (Qt 6)** | Native-looking, mature, handles drag-and-drop, dark mode and high-DPI screens. |
| Packaging | **PyInstaller**, then an **Inno Setup** installer and a portable ZIP, with winget/MSIX later | A normal Windows install experience. |
| Engines | Proven tools wrapped behind one plugin interface (see §4) | FFmpeg, LibreOffice and PyMuPDF are industry standard. No need to reinvent codecs. |
| Automatic tests | GitHub Actions: **Build and test** and **Release** workflows | Linux tests on every commit; Windows tests and the installer build for pull requests into `main` and `main` itself; releases started by hand. |

---

## 3. Architecture

```
┌───────────────────────────────────────────────────────────┐
│  GUI (PySide6)            CLI (azoth …)                │
│  drag & drop, queue,      same features, scriptable       │
│  options                                                  │
└──────────────┬───────────────────────┬────────────────────┘
               │                       │
┌──────────────▼───────────────────────▼────────────────────┐
│  Engine (src/azoth/engine.py)                          │
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

✅ = working now, 🔜 = planned. The exact list of what converts into what is in [FORMATS.md](FORMATS.md).

| Category | Formats | Engine | Status |
|----------|---------|--------|--------|
| **Word ↔ PDF** | DOCX, DOC, ODT, RTF, TXT → PDF | LibreOffice | ✅ |
| **PDF → Word** | PDF → DOCX (also DOC, ODT, RTF via DOCX) | pdf2docx | ✅ |
| **PDF → images / text** | PDF → PNG, JPG, WebP, BMP, multi-page TIFF; PDF → TXT | PyMuPDF | ✅ |
| **Images → PDF** | any image → PDF | Pillow | ✅ |
| PDF tools | merge, split (by page or range), rotate, delete, reorder pages; in the app and the command line | PyMuPDF | ✅ |
| PDF tools | compress (3 levels), add or remove a password (AES-256) | PyMuPDF | ✅ |
| Scanned PDFs, photos of text | OCR → searchable PDF, Word, TXT (English, German, French, Italian) | Tesseract (inside PyMuPDF) | ✅ |
| Spreadsheets | XLSX, XLS, ODS, CSV ↔ each other, → PDF | LibreOffice | ✅ |
| Presentations | PPTX, PPT, ODP ↔ each other, → PDF, → images | LibreOffice | ✅ |
| Images | JPG, PNG, WebP, BMP, TIFF, GIF, ICO, HEIC, AVIF | Pillow, pillow-heif | ✅ |
| Privacy | Remove photo metadata, same format in and out (JPG, PNG, WebP, GIF, TIFF, HEIC, AVIF) | own lossless code, Pillow | ✅ |
| Privacy | Remove document metadata (PDF, DOCX, XLSX, PPTX) | own code, PyMuPDF | ✅ |
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
- [x] CLI: `azoth convert`, `azoth formats`, `azoth pdf merge/split`
- [x] GitHub Actions: tests on Windows and Linux, plus a Windows build artifact
- [x] `PRIVACY.md`, and a test fixture that fails any test that touches the network

### Phase 1: PDF and Office MVP (done: release 0.1.0, repository public)
- [x] Word/Excel/PowerPoint/OpenDocument → PDF and between each other (LibreOffice, hardened profile per job)
- [x] PDF → Word (pdf2docx), with a clear message for scanned PDFs
- [x] PDF → images (one file per page, or multi-page TIFF), PDF → text, images → PDF
- [x] Image conversions with metadata removal by default (GPS/EXIF)
- [x] GUI v1: drag and drop, batch list, target picker, output folder, options, progress, cancel
- [x] "Supported formats" section in the app (open/close, searchable), generated from the converters
- [ ] Test with real-world files: complex Word layouts, large PDFs, Excel with several sheets
- [x] **Microsoft Word engine:** if Word is installed, it does Word → PDF (exact layout); falls back to LibreOffice. *Needs a check on a real Windows PC with Word.*
- [x] **Passwords on Office files** (owner's wish, 23 Nov 2026): add/remove a password on DOCX, XLSX, PPTX (remove also on DOC, XLS, PPT) on the Password page (own sidebar entry since 23 Nov 2026, owner's wish) and `azoth password`; protected files are converted after asking for the password (unlocked only in the job's temp folder; msoffcrypto-tool, MIT). *Owner to check: a protected file made in Office opens here, and a file locked here opens in Office.*
- [x] **Microsoft Excel and PowerPoint engines** (owner's wish, 23 Nov 2026: company PC with Office but no LibreOffice showed "install LibreOffice"): Word, Excel and PowerPoint convert their files to PDF and between their own formats (Word: DOCX, DOC, ODT, RTF, TXT; Excel: XLSX, XLS, ODS, CSV; PowerPoint: PPTX, PPT, ODP). The LibreOffice message only names what nothing installed can do. *Needs a check on the owner's company PC (Excel → PDF, PowerPoint → PDF, XLS → XLSX, PPT → PPTX, a password-protected file, PowerPoint already open).*
- [x] **1:1 quality pass:** photos go into PDFs unchanged (Word/Excel/PowerPoint → PDF and image → PDF), lossless sources stay lossless, JPG at quality 95 with full colour detail, PDF pages as images at 300 DPI
- [x] **Quality levels** (Maximum / High / Smaller files) with minimums that can't be undercut
- [x] Locked dependency versions with hashes
- [x] Target formats sorted by usefulness (e.g. PDF → Word first; DOC/XLS/PPT last); the first one is the default
- [x] Remember settings between sessions (target format, output folder, quality, Word, metadata); stored locally only, removed on uninstall
- [x] Clean uninstall: one storage folder (no registry), file dialog history erased after use, crash leftovers cleaned at start; the uninstaller removes program folder, settings, temp leftovers and its own entries. The automatic build simulates leftovers and fails if anything remains.
- [x] Inno Setup installer: per-user install without admin rights, Start menu entry, optional desktop icon, clean uninstall; tested automatically on every build (install → run → uninstall)
- [x] App icon ("F1": document with a golden seal holding the convert arrows, indigo tile), About window with version, privacy promise, license and component licenses
- [x] **Release 0.1.0** (18 Nov 2026), repository made public, `main` protected, security policy (`SECURITY.md`) and private vulnerability reporting

### Phase 2: PDF power tools and OCR (≈ 4–6 weeks)
- [x] PDF tools in the GUI: merge (with drag-to-reorder), split by range, rotate, delete or reorder pages, page thumbnails. *Done (Nov 2026): lossless (pages copied, not redrawn), bookmarks kept; `pdf_tools.py`, `gui/pdf_tools_page.py`, `azoth pdf split --ranges`, `azoth pdf edit`.*
- [x] Compress PDF (downsample images). *Done (Nov 2026): Light / Balanced / Strong, never below `MIN_DPI` and `MIN_IMAGE_QUALITY`, nothing saved unless at least 1 % smaller; `azoth pdf compress`.*
- [x] Add or remove a password (only with the user's own password). *Done (Nov 2026): AES-256, password never stored, weak-password warning; `azoth pdf password add/remove`.*
  - [x] Merge, Split and Edit pages keep an owner's "no printing / no copying" restrictions in the copy, like Compress does
- [x] OCR: scanned PDF or photo → searchable PDF, then → Word (bundled Tesseract with German, English, French and Italian language packs). *Done (Nov 2026, owner's choices): on the Convert page (scans/photos → Word, TXT; photos → searchable PDF as an option) and as PDF tools → Make searchable / `azoth pdf ocr`; "best" language models (37 MB, fetched by `packaging/fetch_tessdata.py`); the text is an invisible layer, pages stay byte for byte the same.*
  - [x] Turn sideways or upside-down scans automatically before reading. *Done (Nov 2026): only when a page reads badly are the other three directions tried (quick, 100 dpi); such pages are also turned upright (only the rotation setting; owner's wish: a Settings option, on by default).*
  - [ ] Later: Word from scans with layout and pictures (now: the text as plain paragraphs)
  - [ ] Later: several languages in one document (e.g. German + English), more languages
  - [x] A Cancel button and page progress bar for Make searchable on long PDFs
  - [ ] Later: check OCR speed on long PDFs (a few seconds per page now) and make it faster if needed
  - [ ] **Owner's wish (Nov 2026):** OCR → a "real" text PDF like one made from Word (visible, selectable text with exact selection boxes, editable in Word with formatting), as an option next to the 1:1 searchable PDF (picture + invisible text). Needs layout rebuilding (fonts, sizes, columns); the picture would no longer be kept 1:1
- [x] **File name in every PDF tool** (owner's wish, Nov 2026): Merge, Split (folder name), Edit pages, Compress, Password, Make searchable
- [ ] PDF → Excel for tables
- [x] **Remove photo metadata** without changing the format (e.g. JPG → clean JPG): strips GPS location, camera and date, keeps the picture upright. Batch-capable, in the GUI and as `azoth clean`. Also show what metadata a file contains before removing it. *Done (Nov 2026): picture data copied byte for byte, checked pixel by pixel before saving.*
  - [x] Removing metadata from PDF and Office files (author, company, edit history): DOCX, XLSX, PPTX and PDF, content checked unchanged before saving (on `dev`, Nov 2026)
  - [ ] Later: BMP and ICO (they rarely carry metadata); OpenDocument files (ODT, ODS, ODP: `meta.xml`); old DOC/XLS/PPT (today: convert first)
  - [x] A "Show metadata" button (ⓘ) on each photo card, besides the right-click menu (0.4.0)
- [x] **Release 0.2.0** (19 Nov 2026): new look, PDF tools (merge, split, edit pages), remove photo metadata, choose the file name
- [x] **Release 0.3.0** (22 Nov 2026): compress PDF, passwords, OCR, file names in every PDF tool, "Done" card

### Design refresh (timing flexible)
- [x] Mockups first: agree on the look before changing code. *Nov 2026: clickable mockups made (owner's private design canvas): A Windows 11 style with sidebar, B one column with a "Convert 4 photos to JPG" sentence bar, C dark with gold accent; three icon ideas (the drop, the turning page, two pages); a new Supported formats page. **Owner's choice (Nov 2026): style A.** Icon choice postponed.*
- [x] **Light / dark mode setting** (owner's wish, Nov 2026): Settings offers *Follow Windows* (default), *Light* and *Dark*
- [x] **Overall look much slicker and more modern** (owner's wish, Nov 2026): the current window is functional but plain. *Done with style A (Nov 2026); not yet seen on a real Windows PC.*
- [x] Modern Windows 11 look (Fluent style): rounded corners, accent colour; follows Windows light/dark mode. *Own stylesheet on Qt's Fusion style (`gui/theme.py`); the Mica see-through background is not done.*
- [x] Clear layout: sidebar with **Convert**, **PDF tools**, **Supported formats**, **Settings**. *All four entries exist (PDF tools since Nov 2026).*
- [x] Bigger, friendlier drop zone with an icon; files shown as cards with file-type icons, size and their own progress bar
- [x] **Remove button on every file in the list**: a small bin icon (or a "⋯" menu) at the right end of each row, next to the status, instead of "select, then click Remove selected". Keep "Clear list" for removing everything
- [x] **Choose the result's file name** (owner's wish, Nov 2026): "File name" under "Save to", pre-filled with the original's name; for one file at a time (with several files each keeps its own name)
- [x] **Bin button on every PDF in the Merge list** (owner's wish, Nov 2026), like on the Convert page; "Remove" below the list and the Delete key still work
- [x] **Plain-language quality texts** (owner's wish, Nov 2026): "quality 95 / 300 DPI" replaced by what it means for the user; the numbers are in the tooltip
- [x] Target format picker as a grid of format tiles, with the most used ones first
- [x] "Done" notification with **Open file** / **Open folder** buttons; subtle animations. *Done (Nov 2026): a "Done" card that fades in on the Convert page, plus a Windows notification when the app is in the background (Settings can turn it off). Not yet seen on a real Windows PC.*
- [ ] **Rework the app icon** (ideas 1–3 on the design canvas; owner postponed the choice, Nov 2026): the current one (document with a golden seal, design "F1") is fine for now, but from a distance the yellow circle with the two arrows looks like a smiley. Keep the idea (document + transformation), change the seal so it can't be read as a face
- [x] Consistent icon set inside the app (bundled, no web fonts or online assets): line icons drawn in `gui/icons.py`
- [x] **Redesign the "Supported formats" section** to match the new look: cleaner and easier to scan (e.g. format tiles or chips per category, clear "needs LibreOffice" marking, better search)
- [ ] Keep it accessible: keyboard navigation, screen readers, high contrast, scaling to 200 %. *Partly: all colours pass contrast checks (`tests/test_theme.py`), buttons have names for screen readers, focus rings for the keyboard; Windows high-contrast mode and 200 % scaling not yet tested.*
- Options: Qt's built-in Windows 11 style plus our own stylesheet, or the GPL-licensed *PySide6-Fluent-Widgets* library (compatible with our license)

### Technical improvements (from the code review, Nov 2026; schedule as needed)
- [x] **Uninstall button in Settings** (owner's wish, Nov 2026): only in the installed app; starts the normal uninstaller
- [x] **Error log** (owner's wish, Nov 2026, after a crash with mixed PNG and other photos that couldn't be reproduced): details of unexpected errors and hard crashes go to `error-log.txt` in the app's folder; Settings → Error log…; never sent anywhere
- [ ] Find the crash the owner saw in 0.2.0 (several photos, some already PNG, then Convert) once the error log shows it
- [ ] **Faster large batches:**
  - [x] LibreOffice: up to 10 files per start instead of one start per file (`Engine.convert_many`, `Converter.convert_batch`); about 4× faster for 10 Word files
  - [x] Word (Windows): one Word start for up to 10 files instead of one per file. Tested by the owner with real Word (Nov 2026)
  - [x] Photos: up to 4 converted at the same time (`Converter.parallel_safe`); about 4× faster for 16 large photos
  - [ ] PDF → images in parallel: PyMuPDF isn't thread-safe, so this would need separate processes
- [x] **Split the main window code** (`gui/main_window.py`, ~550 lines: layout, state and settings in one file) into smaller parts, ideally before or as part of the design refresh. *Done (Nov 2026): `file_list`, `options_panel`, `output_folder`, `targets` (no Qt) and `worker`; the window looks the same.*
- [ ] **Smaller download** (~140 MB installer): trim unused Qt parts; check whether the PDF → Word engine can work without the full OpenCV package, or replace it
- [x] **PDF → Word progress and cancel** for large PDFs: pdf2docx's steps run page by page, with progress and cancel between pages (on `dev`, Nov 2026)
- [x] Cache the list of possible target formats per source format (computed repeatedly today; fine now, matters with many more formats)

### Phase 3: Audio and video (≈ 4 weeks)
- [ ] FFmpeg plugin with progress parsed from FFmpeg's output
- [ ] Presets: "MP4 for sharing", "MP3 320k", "Extract audio", "Make GIF", "Shrink video"
- [ ] Trim, resolution, bitrate, mute; hardware encoding (NVENC, Quick Sync, AMF)
- [ ] Hardening: `-protocol_whitelist file` so FFmpeg can't reach the network through a malicious playlist file
- [x] **Release 0.3** (0.3.0 and 0.3.1, Nov 2026)

### Phase 4: More formats and convenience (≈ 6–8 weeks, pick by demand)
- [x] **Fully portable version** (on `dev`, Nov 2026: `portable.py`; `portable.txt` only in the ZIP, never in the installer; the build tests the unzipped app; runs from a USB stick, leaves nothing on the PC): the portable ZIP gets a marker file (e.g. `portable.txt`); when the app finds it next to itself, it keeps its settings in a `data` folder beside the program instead of `%APPDATA%`. Add an automatic test that the portable app writes nothing outside its folder. Office formats still need LibreOffice or Word on the PC (a "portable + Office pack" could bundle portable LibreOffice later)
- [x] Command-line program renamed to `azoth-terminal.exe` (owner's wish, 0.4.0); double-clicked it shows a short note instead of opening the app
- [x] Windows Explorer right-click menu: "Convert with Azoth Converter → …" (on `dev`, Nov 2026): up to 6 targets per kind of file, "Remove metadata", "Open in Azoth Converter…"; added and removed by the installer (task, ticked by default), entries generated from the formats (`packaging/make_context_menu.py`); several files → one window, one batch
  - [ ] Windows 11 shows it under "Show more options"; the short Windows 11 menu needs a signed app package (after code signing)
  - [ ] Not in the portable version (it must leave nothing on the PC); maybe later a "Send to" shortcut it can add and remove itself
- [ ] **Image size and quality (owner's wish, Nov 2026):** choose how many pixels a picture should have (e.g. width × height, a percentage, or "longest side 2000 px"), when converting or on its own (same format).
  - [x] Smaller: normal high-quality downscaling (Lanczos), plus **plain enlarging** (smooth bicubic, adds no detail). App: "Picture size" + "Change size only" tile; CLI: `--resize`, `--only-shrink` (on `dev`, Nov 2026). Owner's feedback: "Screen size" instead of "Fit inside", turned for portrait photos; "Longest side" only on the command line; enlarging is normal, "Don't enlarge smaller pictures" optional; ready-made sizes (8K … 640 × 360, percentages) with "Custom size…" last, owner's wish
  - [x] **AI upscaling / "Enhance with AI"** (on `dev`, 23 Nov 2026, `upscale.py`): checkbox under "Picture size"; enlarging adds invented detail, "Keep original size" + AI = improve quality at the same size (sharper, less noise, fewer JPEG blocks; saved as "name (enhanced)"). "Noise removal" Low / Medium / High. CLI `--ai`, `--denoise`. Never the default; pictures that get smaller don't use it; every enhanced file gets a note that the detail is invented.
  - Never the default: originals stay 1:1 unless the user asks. Say clearly that AI-added detail isn't real (not for documents, evidence or ID photos)
  - How it works: Real-ESRGAN `realesr-general-x4v3` + `realesr-general-wdn-x4v3` (BSD-3, ×4, mixed for the noise levels as in Real-ESRGAN's own `--denoise_strength`), fetched at build time by `packaging/fetch_upscale_model.py` (pinned SHA-256, read without PyTorch by a safe unpickler, stored as a 4.5 MB float16 `.npz`). At run time the network is written as an ONNX file in memory and run by **OpenCV's dnn module** (already in the app via pdf2docx), ~4× faster than plain numpy: ~10 s per megapixel of the original on a 4-core cloud machine, ~210 MB memory. Tiles of 256 px with 24 px overlap (max. 1 of 255 levels difference to one whole-picture pass), result resized strip by strip with Pillow's `box` (no seams, little memory). Other sizes than ×4: ×4 then Lanczos (smaller) / bicubic (bigger). Transparency: alpha enlarged normally, hidden colours under transparent pixels filled first (no dark fringes). One AI picture at a time (it uses all cores). 16-bit pictures are refused with a clear message.
  - [ ] Owner to try on Windows with real phone photos: quality, speed on their PC, the wording of the hint.
  - [ ] **Owner's question (23 Nov 2026): a better model?** Option "Best quality (slower)" with Real-ESRGAN `RealESRGAN_x4plus` (BSD-3, ~64 MB, about 15× more work than the current model: minutes per photo on a normal PC). Bigger models (SwinIR, HAT, diffusion like SUPIR) need a graphics card and GBs of download. No model recovers the real detail; bigger ones only guess better. **Measured (23 Nov 2026):** `RealESRGAN_x4plus` (RRDBNet, 67 MB) runs fine in OpenCV dnn (ops: Conv, LeakyRelu, Concat, Resize nearest) but is ~17× slower (~140 s per megapixel of the original on 4 cores). ×2 and JPEG clean-up: hardly visible difference (1–3 % better numbers). ×4 from tiny photos: visibly more natural texture (fur, hair) than the small model. Suggestion: optional "Best quality (slow)" only; owner to decide.
  - [ ] Later ideas: graphics-card speed-up (OpenCV's OpenCL/DirectML, or onnxruntime-directml; more download size), a face-specific model (GFPGAN-style) for portraits, an estimate of the time before starting, "Enhance" as its own tile if the checkbox is hard to find.
- [ ] Watch folders (files dropped in a folder are converted automatically)
- [ ] Data formats (CSV/JSON/XML/YAML/XLSX), Markdown/HTML/EPUB, archives, Camera RAW, SVG
- [ ] Saved presets, optional local conversion history (can be cleared or turned off)
- [ ] **Much later (only when everything else works well):** a preview window: look at a file's pages before converting and the result afterwards (side by side, zoom, select text to check OCR). Viewing only

### Phase 5: Production release 1.0 (≈ 3–4 weeks)
- [ ] **Bundled "Office pack"** so users don't need to install LibreOffice separately (offline installer)
- [ ] Smaller download: trim unused Qt and OpenCV parts, or try Nuitka
- [ ] **Code signing** through the free **SignPath Foundation** program, so Windows SmartScreen doesn't warn users:
  - [x] Two-factor authentication on GitHub
  - [x] Code signing policy page (`CODE_SIGNING.md`), linked from the README and the release notes
  - [ ] Apply on signpath.org (owner); approval can take a few weeks
  - [ ] After approval: SignPath API key as a GitHub secret (owner), then add signing to the Release workflow: build → sign `.exe` files → build installer → sign installer, with manual approval per release
- [ ] SBOM (CycloneDX) and third-party license notices bundled in the app
- [ ] Accessibility (keyboard navigation, screen readers, high contrast)
- [ ] Translations of the app (e.g. German, French, Italian). **Each language added to the app must also be added to the installer** (`packaging/installer.iss`, `[Languages]`), and no installer language without the app: the two always match. Until then both are English only.
- [x] **"Check for updates" button** (owner asked, Nov 2026): Settings → About opens the GitHub Releases page in the browser; the app itself stays offline
- [ ] **Version check inside the app** (owner's wish for later, Nov 2026): the app looks up the newest version itself and says "Update available", then later downloads and installs it. Needs a decision, because it means the app goes online: only when the user clicks (never automatic, see principle 2), ask once before the first check, and only after code signing so a download can be checked as really coming from us
- [ ] Publish on winget and optionally the Microsoft Store (MSIX)

### Phase 6: Other platforms
- [ ] macOS (.dmg, notarized, Apple Silicon and Intel)
- [ ] Linux (AppImage and/or Flatpak)

---

## 6. Data-safety checklist

| Check | How | Status |
|-------|-----|--------|
| No network in the app process | Autouse pytest fixture blocks sockets for every test | ✅ |
| No network from engines (LibreOffice, later FFmpeg) | Automatic test with network blocked at the OS level (firewall rule) | 🔜 |
| Temp files cleaned | Tests check the temp folder after success, failure and cancel | ✅ |
| Metadata stripping | Tests check that GPS and EXIF data is gone, and that rotation is still correct | ✅ |
| LibreOffice hardened | Fresh profile per job: macros disabled, link updates never, update check off | ✅ |
| Originals untouched, no silent overwrite | Tests | ✅ |
| Untrusted input | Fuzz tests on detection and parsers; malicious sample files | 🔜 |
| Supply chain: locked versions | `requirements.lock` / `requirements-dev.lock` with hashes; the automatic builds install with `--require-hashes` | ✅ |
| Supply chain: releases | Signed releases, SBOM | 🔜 |

---

## 7. Testing strategy

- **Unit and integration tests** (`tests/`): every converter, the engine, the CLI and the GUI (pytest-qt, headless).
- **Round-trip tests:** e.g. DOCX → PDF → DOCX keeps headings, text and tables.
- **Office tests** run when LibreOffice is installed. The automatic tests install it on both Windows and Linux.
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
