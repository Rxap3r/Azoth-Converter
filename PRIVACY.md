# Privacy

Azoth Converter is built for people who don't want their files on someone
else's server.

- **Your files never leave your computer.** All conversions run locally. Azoth Converter doesn't upload, sync or share anything.
- **No telemetry.** No analytics, usage statistics, crash reports or tracking of any kind.
- **No account.** Nothing to sign up for.
- **No automatic network access.** The app doesn't connect to the internet on its own. "Check for updates" in Settings only opens the download page in your web browser; the app itself stays offline.
- **No leftovers.** Intermediate files go to a private temporary folder that is deleted when the conversion finishes, fails or is cancelled.
- **Photo metadata is removed by default.** Camera details, date and GPS location are stripped from converted images unless you choose "Keep photo metadata". To remove the metadata without converting, use **Remove metadata only** (or `azoth clean`): the picture stays exactly the same.
- **Video and sound metadata is removed too.** Phone videos record where they were filmed (GPS), the phone model and dates: converted copies don't have them (same "Keep … metadata" setting). **Remove metadata only** does the same for a video or song without converting it: picture and sound stay bit for bit the same. Kept are the title and, for music, the song tags (title, artist, album, track, cover). FFmpeg, which converts video and sound, may only open files on your computer, so a crafted playlist or video can't make it connect to the internet.
- **Your originals are safe.** Source files are never changed, and existing files are never overwritten unless you ask for it.
- **Error log stays on your computer.** If something goes wrong, the details are written to `error-log.txt` in the same folder (Settings → **Error log…**). It is never sent anywhere. It may contain names of files you converted, so look at it before attaching it to a problem report.
- **Clean uninstall.** The app stores its few preferences in one folder (`%APPDATA%\Azoth Converter`), never in the registry. The file dialog's list of recently visited folders is erased right after each use. The right-click menu in Explorer (if you keep that installer option) is the only thing in the registry, and the installer adds and removes it, not the app. When you pick several files there, Windows starts the program once per file; they hand the files to one window through a local channel on your PC that only your own programs can use (protected by a random key in that same folder), never over the network. Uninstalling removes the program, that folder, the right-click menu, any leftover temporary files and the Start menu entries: nothing of the app stays behind.
- **Documents can't run code.** Office documents are opened with macros disabled and external links blocked.

Because Azoth Converter is open source (GPL-3.0), anyone can check these promises in the code.
