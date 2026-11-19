# Changelog

All notable changes to Azoth Converter. New entries go under **Unreleased** as soon as they
are on `dev`; when a version is released, they move into a section for that version.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- **PDF tools** in the app (new sidebar entry): **Merge** PDFs in any order (drag or Move up /
  Move down), **Split** a PDF into single pages or page ranges like "1-3, 5, 8-", and **Edit
  pages**: turn, delete and reorder pages using page previews. The result is saved as a new
  file; the original is never changed.
- Command line: `azoth pdf split --ranges "1-3, 5"` and the new `azoth pdf edit` (`--pages`,
  `--delete`, `--rotate 2=90`).
- **Light and dark look:** under **Settings → Appearance**, choose *Follow Windows* (the default),
  *Light* or *Dark*. The window's title bar follows too.
- Each file in the list has its own **remove** button, its own progress bar, and **Open** /
  **Show in folder** once it's converted.
- **Remove photo metadata** without changing the format or the picture: GPS location, camera,
  date, author, comments, preview pictures and other hidden data are removed from JPG, PNG,
  WebP, GIF, TIFF, HEIC and AVIF files. In the app, choose **Remove metadata only**;
  on the command line, use `azoth clean`. The copy is saved as "name (clean)" next to the
  original, or under the same name in another folder.
- **Show metadata…** (right-click a file in the list) and `azoth clean --show` list what a
  photo contains, for example the place where it was taken.
- Right-click a file in the list to remove it.
- Settings explains (when you point at the setting) in plain words which photo details are removed when converting (location,
  date, camera, preview pictures, captions …) and what is kept.
- **Check for updates…** in Settings: opens the download page in your browser so you can compare
  versions. The app itself never goes online.
- **Choose the file name** of the result (Convert page, under "Save to"): starts as the original's
  name and can be changed when converting one file. With several files, each keeps its own name.
  Names that could reach another folder or that Windows doesn't allow are refused; an existing
  file is still never overwritten.
- `SECURITY.md`: how to report security or privacy problems privately.
- `CODE_SIGNING.md`: code signing policy, needed for free code signing through SignPath Foundation.

### Changed
- **New look** (design "A"): a sidebar with **Convert**, **Supported formats** and **Settings**;
  files shown as cards; the target formats as tiles with a short note on what each is good for;
  quality as three buttons (Maximum / High / Smaller) next to them; the Convert button says what
  will happen ("Convert 3 files to JPG").
- **Supported formats** is now its own page with search, filter buttons per kind of file, and
  conversions that need LibreOffice marked with a dashed outline.
- "Keep photo metadata" and "Use Microsoft Word" moved to **Settings**; the About window opens
  from there.

- PDF tools → Merge: every PDF in the list has its own bin button to remove it (the Delete key
  works too); "Remove" below the list still removes the selected ones.
- Quality: the texts under Maximum / High / Smaller now say in plain words what you get
  (e.g. "Looks the same as the original. Biggest files."); the technical numbers moved to the
  tooltip.

- The app icon is no longer repeated in the sidebar next to the name; it stays in the title
  bar and on the taskbar.
- "Save to" now says "Same folder as the original" instead of "Next to the originals".

### Quality
- Removing metadata never re-compresses the picture: the picture data is copied byte for byte
  (TIFF is rewritten with the same lossless compression). Before saving, the app compares the
  cleaned copy with the original pixel by pixel and checks it again for leftover metadata; if
  either check fails, nothing is saved. Colour profile, orientation and animation are kept.
- PDF tools copy pages exactly as they are (text, pictures, fonts, links, form fields): nothing
  is redrawn or re-compressed. Bookmarks are kept when merging and editing.

### Privacy and safety
- PDF tools save into a private temporary folder first, so a failure never leaves a half-written
  file, and they never overwrite an existing file. Split no longer replaces files of an earlier
  split with the same names.
- JPG → PDF: data that phones hide after the end of a photo (a second picture or the video of
  a "motion photo") and multi-picture indexes are no longer put into the PDF.

### Development
- The "Build and test" workflow file is renamed from `ci.yml` to `build-and-test.yml`, to match its name.
- Runs of "Build and test" that build the Windows download are titled "📦 With download · …".
- Every colour of the light and dark look is checked automatically for readable contrast
  (WCAG: 4.5:1 for text).
- The main window's code is split into parts (file list, options, output folder, target
  choice, background worker), to prepare the design refresh. The window looks and works the
  same; new tests cover each part on its own.
- Pull requests into `main` always get the full check, also for documentation-only changes,
  so the checks can be required before merging.
- Faster automatic tests: every commit to `dev` runs only the Linux tests; pull requests into `main` also run
  the Windows tests and build and test the installer; documentation-only changes start no run.
- New **Release** workflow: started by hand on `main`, it tests everything, builds the installer
  and publishes the GitHub Release with the tag `v<version>`.
- Pull requests into `main` are only opened when the owner asks for one.
- Faster checks without weaker tests: LibreOffice and the Python packages install at the same
  time, and the installer is built and tested while the test suites run. A release is published
  only after every test and the installer test passed, using exactly the files that were tested.
- The automatic test workflow is now called **Build and test** (was "CI").
- The Actions tab lists only **Build and test** and **Release**; their shared steps are now reusable actions
  in `.github/actions/` instead of extra workflows.

## [0.1.0] - 2026-11-18

First release.

### Added
- Offline conversion of documents, PDFs and images on Windows; nothing is uploaded.
- **Word → PDF** with Microsoft Word when installed (exact layout), otherwise LibreOffice.
- **PDF → Word** (editable DOCX with tables and images), PDF → images (one per page or
  multi-page TIFF) and PDF → text.
- Excel, PowerPoint and OpenDocument formats ↔ each other and → PDF; CSV ↔ Excel.
- Images: JPG, PNG, WebP, HEIC, AVIF, TIFF, GIF, BMP, ICO, and any image → PDF.
- PDF merge and split (command line `azoth`).
- Quality levels (Maximum / High / Smaller files) with minimums that can't be undercut.
- Target formats sorted by usefulness; the app remembers the last choice per kind of file.
- "Supported formats" section in the app; full list in `docs/FORMATS.md`.
- Windows installer (no admin rights needed) and portable ZIP; app icon; About window.

### Quality
- Photos in Word/Excel/PowerPoint and image → PDF are embedded unchanged (no re-compression).
- Lossless images stay lossless; JPG output at quality 95 with full colour detail;
  PDF pages as images at 300 DPI.

### Privacy and safety
- No network access, telemetry or account. Photo metadata (GPS, camera, date) removed by default.
- Office documents opened with macros disabled and external links blocked.
- Originals are never changed; existing files are never overwritten.
- Clean uninstall: program folder, settings, temporary files and registry entries are removed.

[Unreleased]: https://github.com/Rxap3r/Azoth-Converter/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Rxap3r/Azoth-Converter/releases/tag/v0.1.0
