# Changelog

All notable changes to Azoth Converter. New entries go under **Unreleased** as soon as they
are on `dev`; when a version is released, they move into a section for that version.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- **Passwords on Word, Excel and PowerPoint files:** PDF tools → Password now also takes
  DOCX, XLSX and PPTX files: add a password (AES-256, the same encryption as current
  Office, so Office opens them as usual) or remove it from your own file (also from older
  DOC, XLS and PPT). Command line: `azoth password add budget.xlsx` (also
  `azoth pdf password`).
- **Converting password-protected Office files:** the app asks for the password (it checks
  it right away, and it is never saved), then converts the file. Cancel skips the file.
  The converted file has no password. Works with Microsoft Office and with LibreOffice.
  The command line asks too.

- **Microsoft Excel and PowerPoint:** where they're installed, they now convert their own
  files to PDF (exact layout), like Word already did. Word, Excel and PowerPoint also save
  their other formats (e.g. DOC → DOCX, XLS → XLSX, XLSX → CSV, PPT → PPTX, ODT, ODS, ODP),
  so on a PC with Microsoft Office, LibreOffice isn't needed. If Office fails, LibreOffice
  steps in when it's installed.
- The "LibreOffice is missing" message now only appears for conversions nothing else on
  the PC can do, and says which ones (e.g. "PowerPoint files need LibreOffice or Microsoft
  Office"). The list of formats counts Microsoft Office as installed. Settings: "Use
  Microsoft Office" covers Word, Excel and PowerPoint; command line: `--no-office`.

- **Enhance with AI:** under **Picture size**, "Enhance with AI" makes enlarged photos
  sharp, with new detail the AI invents, instead of smooth and blurry. With "Keep original
  size" (saved as "name (enhanced)"), photos keep their size and get sharper, with less
  noise and fewer JPEG blocks. "Noise removal" (Low / Medium / High) sets how strongly
  noise is smoothed away; Low keeps fine grain. Never on by default; pictures that get
  smaller don't use it. Shows progress and can be cancelled. Command line: `--ai`,
  `--denoise low|medium|high`.

### Privacy and safety

- Protected Office files are unlocked only into the job's private temporary folder, which
  is always deleted; Office and LibreOffice never see the password. Passwords are never
  stored. New library: msoffcrypto-tool (MIT, works offline), with cryptography and
  olefile (about 5 MB more download).
- Excel and PowerPoint run like Word: hidden, macros off, links not updated, files opened
  read-only from a private copy. Password-protected Office files are refused with a clear
  message before Office could ask for the password. If PowerPoint is already open, it stays
  open with the user's own presentations.
- The AI runs entirely on this computer (the Real-ESRGAN model, BSD-3-Clause, built into
  the app as plain numbers, no code; OpenCV, already part of the app, runs it). Nothing is
  downloaded or uploaded. The app says on every enhanced file that the added detail is
  invented, and advises against using it for documents, evidence or ID photos.

### Development

- `packaging/fetch_tessdata.py` now also fetches the AI model (two pinned, hash-checked
  files) through `packaging/fetch_upscale_model.py`, which reads them without PyTorch and
  without running anything from them, and saves the weights as a 4.5 MB `.npz`.
- The automatic Windows build now also checks "Enhance with AI" in the finished program
  (a small transparent picture enlarged with AI), next to the text recognition check.
- The app's window tests now clean up memory only on the main thread, like the app itself
  (a Windows test crashed while a picture was enhanced in the background), and a hard
  crash in a test is reported with its location again.

## [0.4.0] - 2026-11-22

### Added

- **Change picture size:** photos can be made smaller or bigger while converting, or
  saved in the same format with only a new size ("Change size only", saved as
  "name (resized)"). Choose a screen size (8K, 4K, QHD, Full HD, HD …, turned for portrait
  photos), a width, a height or a percentage, from ready-made sizes or "Custom size…".
  Proportions are always kept. "Don't enlarge smaller pictures" leaves small ones as they
  are. Each resized file shows its new size (e.g. "· 1920 × 1280 px"). Command line:
  `--resize 1920x1080`, `--resize 2000` (longest side), `--resize 50%`, `--only-shrink`.
- **Portable mode:** when a file `portable.txt` lies next to the program, the app keeps its
  settings and error log in a `data` folder beside it, and its temporary files in
  `data\temp`, instead of on the PC. Nothing to uninstall: delete the folder. The "Done"
  notification is off by default there (Windows remembers every app that shows one).
  The portable ZIP now contains this file (the installer never does), so it is fully
  portable.
- Photos in the list show their size in pixels next to the file size
  (e.g. "4032 × 3024 px · 3.2 MB").
- **"Show metadata" button** (ⓘ) on every photo in the list, so you can see what's hidden
  in it (location, camera, date …) without the right-click menu.

### Changed

- The command-line program in the Windows download is now called **azoth-terminal.exe**
  (was azoth.exe), so it's clear which one is the app. Double-clicking it shows a short note
  on how to use it instead of opening the app. Updating removes the old azoth.exe.

### Quality

- Pictures keep all their pixels unless you choose a size. Making smaller uses Lanczos
  (sharp, clean), enlarging uses smooth bicubic; transparent edges stay clean. Kept
  metadata no longer claims the old pixel size.

### Fixed

- The app could crash ("access violation") while converting several photos at once:
  Python's memory clean-up could run in a conversion thread and free parts of the window.
  It now runs only in the main thread, and all picture format readers load at start-up.
  This may also have been the crash seen in 0.2.0 with several photos.

### Development

- The possible target formats and conversion routes are worked out once and remembered,
  instead of again for every change in the list.
- The Windows build also makes and tests the portable ZIP: unzipped, it must convert, start
  and leave nothing in `%APPDATA%`, the temp folder or the registry. Manual test builds
  offer the ZIP for download too.

## [0.3.1] - 2026-11-22

### Added

- When LibreOffice isn't installed, a "Download LibreOffice…" button (on the Convert page
  and under Supported formats) opens its official download page in your browser. The app
  itself still never goes online.
- When Microsoft Word can't convert a file and LibreOffice is used instead, the file now
  says so ("Word failed, LibreOffice was used"), with Word's reason in the tooltip and in
  the error log. Before, this happened silently.

### Changed

- Converting many Word, Excel or PowerPoint files with LibreOffice is much faster: up to
  10 files are now done in one LibreOffice start instead of one start per file (10 Word
  files to PDF: about 4 times faster in our test). The results are the same; a file that
  fails is tried again on its own, so its error message stays clear.
- Converting many photos is much faster: up to 4 are converted at the same time (one
  processor core stays free so the window stays responsive). 16 large photos to PNG: about
  4 times faster in our test. The files are exactly the same as before.
- Converting many Word files to PDF with Microsoft Word is faster: Word now starts once
  for up to 10 files instead of once per file. A file Word can't convert is tried again
  on its own and then with LibreOffice, as before.

### Fixed

- Word → PDF with Microsoft Word never actually worked: Word refused how the options for
  opening the document were passed, and LibreOffice silently took over. The options are now
  passed the way Word expects.
- Settings: the text under "Check for updates", "About" and "Error log" no longer covers
  those buttons with larger Windows text.

### Privacy and safety

- The code signing policy, the README and the release notes now say clearly that the
  downloads are not signed yet; signing is planned.
- Merge, Split and Edit pages now keep a PDF's restrictions (for example "no printing" or
  "no copying") in the new file, like Compress already did. Split and Edit pages keep the
  original lock, so the owner's password still removes it. A merged PDF allows only what
  every one of its restricted files allows; to lift that, remove the restrictions from the
  originals first.

## [0.3.0] - 2026-11-22

### Added

- **Compress PDF** (PDF tools → Compress, or `azoth pdf compress`): saves a smaller copy. Three
  levels: *Light* (no quality loss, only tidies up the file), *Balanced* (very sharp pictures
  reduced to 200 dpi) and *Strong* (pictures at 150 dpi as JPG). Text, links, bookmarks and form
  fields stay as they are. Shows how much smaller the file got; if it can't get smaller,
  nothing is saved.
- **Password** (PDF tools → Password, or `azoth pdf password add/remove`): lock a copy of a PDF
  with a password (AES-256, the strongest encryption in the PDF standard), or save an unlocked
  copy of your own PDF with its password. The password is never saved, the fields are cleared
  right after use, and the app warns about passwords that are easy to guess.
- **Text recognition (OCR), fully offline**, in English, German, French and Italian:
  - scanned PDFs → Word or text (before, a scan gave an error);
  - photos and scans (JPG, PNG, TIFF, HEIC …) → Word or text;
  - photos → PDF can now make the text searchable (*Make the text searchable* on the Convert page,
    or `azoth convert --ocr`);
  - **Make searchable** in PDF tools (or `azoth pdf ocr`): adds the recognised text to a scanned
    PDF invisibly, so you can search, select and copy it.
  - a searchable scan (picture with invisible text) → Word now gives the text, not one big
    picture.
  - pages that are sideways or upside down are read and **turned the right way up** (only the
    page's direction changes, the picture stays exactly the same). Can be turned off in
    Settings, or with `--keep-rotation`. Normal pages are not slowed down by this check;
  - Make searchable shows a progress bar and has a **Cancel** button (nothing is saved when
    cancelled).
  The language is chosen next to the format tiles and remembered; the first time it follows the
  computer's language.
- **"Done" card** on the Convert page when a conversion finishes: "Done! 4 files converted"
  (or how many failed), with **Open file** (one result) and **Open folder** buttons. It fades in
  gently.
- **Windows notification** when a conversion or a PDF tool finishes while the app is in the
  background. Can be turned off in Settings. Shown by Windows itself; nothing is sent anywhere.
- PDF tools warn when a PDF is digitally signed, because a new copy can't keep the signature valid.

### Changed

- **Choose the result's name in every PDF tool:** Merge, Split (folder name),
  Edit pages, Compress, Password and Make searchable now have a *File name* field next to
  *Save to*, filled in with the suggested name. Existing files are still never overwritten.
- Edit pages: the buttons "Move earlier" and "Move later" are now "◀ Move" and "Move ▶", the
  direction the page moves in the page grid.

### Fixed

- The app no longer freezes ("Not responding") while text recognition reads a page: the
  reading now runs in a helper process of the app, on this computer as before.
- Settings: the buttons under *About* were cut off by the text below them when the window
  was too low (e.g. with larger text in Windows). The page now scrolls instead, like the
  choices next to the format tiles.

### Quality

- Compress never shrinks pictures below 150 dpi or saves them below JPG quality 75, and photos
  that don't need shrinking keep their original data byte for byte (no second JPG loss).
- The hidden text follows the page's direction, also on turned pages, and uses a font whose
  height every PDF viewer reads the same way (Firefox, Chrome, Edge and others), so selecting
  text marks the right words (in Edge and Firefox the selection used to sit too low).
  Checked letter by letter in the tests.
- Text recognition never changes the pages: the text is added as an invisible layer, the
  pictures stay byte for byte the same, and pages that already have text are left alone. Pages
  are read at 300 dpi with the most accurate ("best") language models.

### Privacy and safety

- Removing a password needs the PDF's own password; restrictions set with an owner password
  (no printing or copying) need the owner password. Compress keeps such restrictions.

### Development

- The OCR language files are not in git: `packaging/fetch_tessdata.py` downloads them (pinned
  version, SHA-256 checked, tried again up to 5 times if the server is busy) for development,
  tests and the build. The build stops if they are missing, and the built app must read the
  sample scan before the installer is made.

## [0.2.1] - 2026-11-21

### Added
- **Error log:** if something goes wrong, the details are saved in a file on your computer
  (Settings → **Error log…**) and a short message is shown instead of the app just closing.
  Hard crashes inside a library are written there too. The log is never sent anywhere and is
  removed by the uninstaller.
- **Uninstall…** at the bottom of Settings (installed app only): asks first, then closes the app
  and starts the normal uninstaller. Your own and converted files are not touched.

### Changed
- **Open output folder** (under the Convert button) only appears when all results are in one
  folder. When they are in different folders, use **Show in folder** on each file.
- Adding or removing files clears "Finished" and the progress bar of the last conversion.
- Installing a new version over an old one first removes the old program libraries, so no
  outdated files are left behind. Your settings are kept. The automatic build tests this.

### Development
- Test and build jobs have a time limit (30 min for tests, 45 min for the installer), so a
  stuck run stops instead of running for hours.

## [0.2.0] - 2026-11-19

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
- A push no longer cancels a test build of the same branch that was started by hand.
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

[Unreleased]: https://github.com/Rxap3r/Azoth-Converter/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/Rxap3r/Azoth-Converter/compare/v0.3.1...v0.4.0
[0.3.1]: https://github.com/Rxap3r/Azoth-Converter/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/Rxap3r/Azoth-Converter/compare/v0.2.1...v0.3.0
[0.2.1]: https://github.com/Rxap3r/Azoth-Converter/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/Rxap3r/Azoth-Converter/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Rxap3r/Azoth-Converter/releases/tag/v0.1.0
