# Security policy

Azoth Converter exists to keep files private, so security and privacy problems are taken seriously.

## Reporting a problem

**Please don't report security or privacy problems in a public issue.** Report them privately instead:

1. Open the repository's **Security** tab.
2. Click **Report a vulnerability**.
3. Describe what you found.

Only the maintainer can see these reports.

Helpful details:

- what happens and what you expected instead;
- steps to reproduce it, and a sample file if one is needed. Don't send files that contain personal data;
- the Azoth Converter version (shown under **About**) and your Windows version.

This is a small volunteer project. You'll get a reply as soon as possible, usually within a week. Once a fix is released, you'll be credited in the release notes if you'd like.

## What counts

Anything that breaks the promises in [PRIVACY.md](PRIVACY.md), for example:

- the app connecting to the internet, or sending or leaking file contents;
- files, settings or temporary data left behind that shouldn't be, including after uninstalling;
- a document managing to run code (macros, scripts) during a conversion;
- originals being changed, or existing files being overwritten without being asked;
- photo location or other metadata surviving when it should have been removed;
- problems with the installer or the published downloads.

Bugs in LibreOffice or Microsoft Word themselves are best reported to those projects. Do tell us, though, if Azoth Converter's protections around them don't work.

## Supported versions

Only the latest release receives fixes. Please check that a problem still happens with the newest version from the [Releases page](https://github.com/Rxap3r/Azoth-Converter/releases/latest).
