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

[Files]
Source: "dist\AzothConverter\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Azoth Converter"; Filename: "{app}\AzothConverter.exe"
Name: "{autodesktop}\Azoth Converter"; Filename: "{app}\AzothConverter.exe"; Tasks: desktopicon

[Registry]
; The app's saved preferences: removed again on uninstall, so nothing is left behind.
Root: HKCU; Subkey: "Software\Azoth Converter"; Flags: uninsdeletekey dontcreatekey

[Run]
Filename: "{app}\AzothConverter.exe"; Description: "{cm:LaunchProgram,Azoth Converter}"; Flags: nowait postinstall skipifsilent
