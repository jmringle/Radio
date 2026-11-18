; Inno Setup script: wraps the PyInstaller folder (dist\FT8 Forecast) in one installer, FT8-Forecast-Windows-Setup.exe.
; Built by .github/workflows/ft8-forecast-app.yml, which runs from the ft8-forecast folder and passes the version:
;   ISCC.exe /DAppVersion=0.1.0 packaging\ft8forecast.iss
;
; Why an installer and not a zip: Windows marks a downloaded zip as "from the internet", Explorer copies
; that mark onto every file it extracts, and .NET then refuses to load the window's Python.Runtime.dll
; ("Failed to resolve Python.Runtime.Loader.Initialize"). Files an installer writes don't get the mark.
; Only the setup file itself is marked, which at most makes SmartScreen ask once. Same fix as dipstick.iss.
; Paths below are relative to this file (packaging\).
;
; The app keeps its database, settings and error log in %APPDATA%\FT8 Forecast, not in the install
; folder, so uninstalling leaves your imported data in place.

#ifndef AppVersion
  #error Pass the version: ISCC.exe /DAppVersion=0.1.0 packaging\ft8forecast.iss
#endif

[Setup]
; Never change AppId: it's how Windows knows a newer setup is an update of the same app.
AppId={{FD4B3BBE-8D50-416C-A3FE-FF841F0C3206}
AppName=FT8 Forecast
AppVersion={#AppVersion}
AppPublisher=jmringle
AppPublisherURL=https://github.com/jmringle/Radio
DefaultDirName={autopf}\FT8 Forecast
DefaultGroupName=FT8 Forecast
DisableProgramGroupPage=yes
; Per user by default (no administrator needed; installs under %LOCALAPPDATA%\Programs). The setup's
; first screen still offers "all users" to anyone who wants it.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
; The build is 64-bit (GitHub's windows-latest runner).
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=FT8-Forecast-Windows-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\FT8 Forecast.exe
UninstallDisplayName=FT8 Forecast

[Files]
; The whole PyInstaller folder: FT8 Forecast.exe and the _internal folder beside it.
Source: "..\dist\FT8 Forecast\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\FT8 Forecast"; Filename: "{app}\FT8 Forecast.exe"
Name: "{autodesktop}\FT8 Forecast"; Filename: "{app}\FT8 Forecast.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; Flags: unchecked

[Run]
Filename: "{app}\FT8 Forecast.exe"; Description: "Start FT8 Forecast"; Flags: nowait postinstall skipifsilent
