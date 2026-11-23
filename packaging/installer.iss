; Inno Setup script for the Windows installer.
; Build after PyInstaller (from the packaging folder):
;   iscc /DAppVersion=0.1.0 installer.iss
; Result: packaging\Output\AzothConverter-Setup-<version>.exe

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
; Never change AppId: Windows uses it to recognise updates of the same app.
AppId={{93ED8031-42A0-4035-882F-06305DF2F0A3}
AppName=Azoth Converter
AppVersion={#AppVersion}
AppVerName=Azoth Converter {#AppVersion}
AppPublisher=Azoth Converter contributors
AppComments=Offline file converter. Your files never leave this computer.
; Installs for the current user without admin rights by default;
; the user can choose "install for all users" (needs admin) in the dialog.
PrivilegesRequired=lowest
; Tells Explorer to reload its right-click menus after installing or removing them.
ChangesAssociations=yes
PrivilegesRequiredOverridesAllowed=dialog
DefaultDirName={autopf}\Azoth Converter
DefaultGroupName=Azoth Converter
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\AzothConverter.exe
UninstallDisplayName=Azoth Converter
OutputDir=Output
OutputBaseFilename=AzothConverter-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

[Languages]
; Keep in sync with the app: only languages the app itself is translated into.
; When the app gets a new language, add it here too (Inno Setup ships official
; translations, e.g. "compiler:Languages\German.isl").
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "contextmenu"; Description: "Add ""Convert with Azoth Converter"" to the right-click menu of files"; GroupDescription: "Explorer:"

[Files]
Source: "dist\AzothConverter\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; Updates: remove the old version's program libraries first, so files a newer version no
; longer uses can't linger and get loaded by mistake. Settings (in %APPDATA%) are not touched.
Type: filesandordirs; Name: "{app}\_internal"
; Before 0.4.0 the command-line program was called azoth.exe (now azoth-terminal.exe).
Type: files; Name: "{app}\azoth.exe"

[Icons]
Name: "{autoprograms}\Azoth Converter"; Filename: "{app}\AzothConverter.exe"
Name: "{autodesktop}\Azoth Converter"; Filename: "{app}\AzothConverter.exe"; Tasks: desktopicon

[Registry]
; The app keeps no settings in the registry, but early test builds did: clean those up too.
Root: HKCU; Subkey: "Software\Azoth Converter"; Flags: uninsdeletekey dontcreatekey
; The Explorer right-click menu (task "contextmenu"); removed again on uninstall.
#include "context_menu.iss"

[UninstallDelete]
; Clean uninstall: nothing of the app stays on the computer.
; The whole program folder, also files that weren't part of the installation.
Type: filesandordirs; Name: "{app}"
; Saved preferences and the file dialog's data (the app's only storage folder).
Type: filesandordirs; Name: "{userappdata}\Azoth Converter"
; Temporary job folders left behind if the app was ever force-closed mid-conversion.
Type: filesandordirs; Name: "{%TEMP}\azoth-*"

[Run]
Filename: "{app}\AzothConverter.exe"; Description: "{cm:LaunchProgram,Azoth Converter}"; Flags: nowait postinstall skipifsilent
