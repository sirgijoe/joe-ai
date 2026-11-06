; Joe for Windows: Inno Setup script. Built by .github/workflows/release.yml:
;   iscc /DAppVersion=2.0.0 /DSourceDir=..\build\windows /DOutputName=Joe-Setup-2.0.0-windows-x64 installer\joe.iss
; SourceDir holds Joe's files plus a private Python (python\pythonw.exe), so nobody has to
; install Python first. Installs for this user only (no admin prompt) into
; %LOCALAPPDATA%\Programs\Joe. The uninstaller removes only that folder: Documents\Joe-ai
; (your work), settings and downloaded add-ons are never touched.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\build\windows"
#endif
#ifndef OutputName
  #define OutputName "Joe-Setup-" + AppVersion + "-windows-x64"
#endif

[Setup]
AppId={{6A1E0E2B-4F0B-4C55-9E7A-01000001A149}
AppName=Joe
AppVersion={#AppVersion}
AppVerName=Joe {#AppVersion}
AppPublisher=Joe contributors
AppPublisherURL=https://github.com/sirgijoe/joe-ai
AppSupportURL=https://github.com/sirgijoe/joe-ai/issues
AppUpdatesURL=https://github.com/sirgijoe/joe-ai/releases
DefaultDirName={localappdata}\Programs\Joe
DefaultGroupName=Joe
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
LicenseFile={#SourceDir}\LICENSE
OutputDir=..\dist
OutputBaseFilename={#OutputName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
UninstallDisplayName=Joe
UninstallDisplayIcon={app}\python\pythonw.exe

[Tasks]
Name: "desktopicon"; Description: "Put a Joe shortcut on the desktop"; GroupDescription: "Shortcuts:"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; old program files from an earlier version (never user data: that lives elsewhere)
Type: filesandordirs; Name: "{app}\joeai"

[Icons]
Name: "{group}\Joe"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\Joe.pyw"""; WorkingDir: "{app}"; Comment: "Joe, your local AI helper"
Name: "{group}\Uninstall Joe"; Filename: "{uninstallexe}"
Name: "{userdesktop}\Joe"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\Joe.pyw"""; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\Joe.pyw"""; WorkingDir: "{app}"; Description: "Open Joe now"; Flags: nowait postinstall skipifsilent
; an update started from inside Joe runs /SILENT: open Joe again afterwards
Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\Joe.pyw"""; WorkingDir: "{app}"; Flags: nowait; Check: WizardSilent

[UninstallRun]
; the night shift's Task Scheduler entry (Setup > General), if it was ever turned on
Filename: "{sys}\schtasks.exe"; Parameters: "/Delete /F /TN ""Joe night shift"""; Flags: runhidden; RunOnceId: "JoeNightShift"

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
