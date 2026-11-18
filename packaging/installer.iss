; Inno Setup script for the Windows installer.
; Build after PyInstaller (from the packaging folder):
;   iscc /DAppVersion=0.1.0 installer.iss
; Result: packaging\Output\FileConverter-Setup-<version>.exe

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
; Never change AppId: Windows uses it to recognise updates of the same app.
AppId={{6D2C2AFB-18AC-401F-A91E-168805E44888}
AppName=File-Converter
AppVersion={#AppVersion}
AppVerName=File-Converter {#AppVersion}
AppPublisher=File-Converter contributors
AppComments=Offline file converter. Your files never leave this computer.
; Installs for the current user without admin rights by default;
; the user can choose "install for all users" (needs admin) in the dialog.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DefaultDirName={autopf}\File-Converter
DefaultGroupName=File-Converter
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\FileConverter.exe
UninstallDisplayName=File-Converter
OutputDir=Output
OutputBaseFilename=FileConverter-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "german"; MessagesFile: "compiler:Languages\German.isl"
Name: "french"; MessagesFile: "compiler:Languages\French.isl"
Name: "italian"; MessagesFile: "compiler:Languages\Italian.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "dist\FileConverter\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\File-Converter"; Filename: "{app}\FileConverter.exe"
Name: "{autodesktop}\File-Converter"; Filename: "{app}\FileConverter.exe"; Tasks: desktopicon

[Registry]
; The app's saved preferences: removed again on uninstall, so nothing is left behind.
Root: HKCU; Subkey: "Software\File-Converter"; Flags: uninsdeletekey dontcreatekey

[Run]
Filename: "{app}\FileConverter.exe"; Description: "{cm:LaunchProgram,File-Converter}"; Flags: nowait postinstall skipifsilent
