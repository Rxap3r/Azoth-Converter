# Code signing policy

Free code signing provided by [SignPath.io](https://about.signpath.io/), certificate by [SignPath Foundation](https://signpath.org/).

## What is signed

For each release, these files are signed:

- the installer `AzothConverter-Setup-<version>.exe`;
- the programs inside the installer and the portable ZIP, `AzothConverter.exe` and `azoth.exe`.

Every signed file is built automatically by GitHub Actions (the **Release** workflow in this
repository), directly from the source code on the `main` branch. Nothing is built or signed on
a personal computer. Before a release is signed:

- all tests run on Linux and Windows;
- the installer is installed, started and uninstalled on a clean Windows machine.

The signing request then has to be approved by hand.

## Team roles

| Role | Who |
|---|---|
| Committers and reviewers | [Rxap3r](https://github.com/Rxap3r) (maintainer). Code changes reach `main` only through reviewed pull requests with all required checks passing. Changes prepared with the help of an AI coding assistant are reviewed the same way. |
| Approvers (approve each signing request) | [Rxap3r](https://github.com/Rxap3r) |

All team members use two-factor authentication for GitHub and SignPath.

## Contributions from others

Pull requests from people outside the team are reviewed by the maintainer before they are
merged. Particular care goes to the build scripts (`.github/`, `packaging/`) and dependency
changes (`pyproject.toml`, `requirements*.lock`), because they decide what ends up in the
signed files.

## Privacy

This program will not transfer any information to other networked systems unless specifically
requested by the user or the person installing or operating it. See [PRIVACY.md](PRIVACY.md).

## Third-party components

The app bundles open-source components such as Qt, Pillow, PyMuPDF and pdf2docx. They are listed
with their licenses in the app under **About**. LibreOffice and Microsoft Word are not bundled;
the app only uses them if they are already installed.
