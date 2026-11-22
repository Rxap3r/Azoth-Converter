<!--
Template for release notes. Copy to docs/releases/v<version>.md, fill in the parts
in <angle brackets>, and keep the "Downloads" section as it is (update the version).
Base "What's new" on the version's section in CHANGELOG.md, in plain language.
-->
<One or two sentences: what this version is about.>

## What's new

- <Change, in plain language>

## Downloads

| File | What it is |
|---|---|
| **AzothConverter-Setup-<version>.exe** | **Installer (recommended).** Installs the app with a Start menu entry and a clean uninstall under *Settings → Apps*. No admin rights needed. |
| **AzothConverter-portable-<version>.zip** | **Portable version, no installation.** Unzip the folder anywhere (also a USB stick) and run `AzothConverter.exe`; to remove it, delete the folder. Same app as the installer, but it keeps its settings and temporary files in a `data` folder next to itself, so nothing is left on the computer. |
| Source code (zip / tar.gz) | Added by GitHub to every release: the project's code at this version. Only needed by developers. |

The files aren't signed yet, so Windows may show "Windows protected your PC": click **More info → Run anyway**.
Code signing is planned: [code signing policy](https://github.com/Rxap3r/Azoth-Converter/blob/main/CODE_SIGNING.md)
For Word, Excel and PowerPoint formats, install the free [LibreOffice](https://www.libreoffice.org/download/) (not needed for PDFs and images, or for Word → PDF when Microsoft Word is installed).

## Known limitations

- <Anything users should know>
