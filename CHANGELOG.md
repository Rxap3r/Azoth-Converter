# Changelog

All notable changes to Azoth Converter. New entries go under **Unreleased** as soon as they
are on `dev`; when a version is released, they move into a section for that version.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- `SECURITY.md`: how to report security or privacy problems privately.
- `CODE_SIGNING.md`: code signing policy, needed for free code signing through SignPath Foundation.

### Development
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
