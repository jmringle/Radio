; Inno Setup script: wraps the PyInstaller folder (dist\Dipstick) in one installer, dipstick-Windows-Setup.exe.
; Built by .github/workflows/dipstick-app.yml, which runs from the dipstick folder and passes the version:
;   ISCC.exe /DAppVersion=0.1.0 packaging\dipstick.iss
;
; Why an installer and not a zip: Windows marks a downloaded zip as "from the internet", Explorer copies
; that mark onto every file it extracts, and .NET then refuses to load the window's Python.Runtime.dll
; ("Failed to resolve Python.Runtime.Loader.Initialize"). Files an installer writes don't get the mark.
; Only the setup file itself is marked, which at most makes SmartScreen ask once.
; Paths below are relative to this file (packaging\).

#ifndef AppVersion
  #error Pass the version: ISCC.exe /DAppVersion=0.1.0 packaging\dipstick.iss
#endif

[Setup]
; Never change AppId: it's how Windows knows a newer setup is an update of the same app.
AppId={{A6F20594-B242-4A23-BF73-A3ACC9549172}
AppName=Dipstick
AppVersion={#AppVersion}
AppPublisher=jmringle
AppPublisherURL=https://github.com/jmringle/Radio
DefaultDirName={autopf}\Dipstick
DefaultGroupName=Dipstick
DisableProgramGroupPage=yes
; Per user by default (no administrator needed; installs under %LOCALAPPDATA%\Programs). The setup's
; first screen still offers "all users" to anyone who wants it.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
; The build is 64-bit (GitHub's windows-latest runner).
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=dipstick-Windows-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\Dipstick.exe
UninstallDisplayName=Dipstick

[Files]
; The whole PyInstaller folder: Dipstick.exe and the _internal folder beside it.
Source: "..\dist\Dipstick\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\Dipstick"; Filename: "{app}\Dipstick.exe"
Name: "{autodesktop}\Dipstick"; Filename: "{app}\Dipstick.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; Flags: unchecked

[Run]
Filename: "{app}\Dipstick.exe"; Description: "Start Dipstick"; Flags: nowait postinstall skipifsilent
