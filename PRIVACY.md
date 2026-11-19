# Privacy

Azoth Converter is built for people who don't want their files on someone
else's server.

- **Your files never leave your computer.** All conversions run locally. Azoth Converter doesn't upload, sync or share anything.
- **No telemetry.** No analytics, usage statistics, crash reports or tracking of any kind.
- **No account.** Nothing to sign up for.
- **No automatic network access.** The app doesn't connect to the internet on its own. A future "Check for updates" feature will only run when you click it.
- **No leftovers.** Intermediate files go to a private temporary folder that is deleted when the conversion finishes, fails or is cancelled.
- **Photo metadata is removed by default.** Camera details, date and GPS location are stripped from converted images unless you choose "Keep photo metadata". To remove the metadata without converting, use **Remove metadata only** (or `azoth clean`): the picture stays exactly the same.
- **Your originals are safe.** Source files are never changed, and existing files are never overwritten unless you ask for it.
- **Clean uninstall.** The app stores its few preferences in one folder (`%APPDATA%\Azoth Converter`), never in the registry. The file dialog's list of recently visited folders is erased right after each use. Uninstalling removes the program, that folder, any leftover temporary files and the Start menu entries: nothing of the app stays behind.
- **Documents can't run code.** Office documents are opened with macros disabled and external links blocked.

Because Azoth Converter is open source (GPL-3.0), anyone can check these promises in the code.
