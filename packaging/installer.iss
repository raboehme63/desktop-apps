; Inno Setup 6 script. Compiled by packaging/build.ps1 when ISCC.exe is on PATH.
; Application Python sources are not modified.

#ifndef MyAppVersion
#define MyAppVersion "1.0.0"
#endif

#define MyAppName "Reisetagebuch"
#define MyAppPublisher "TravelJournal"
#define MyAppExeName "Reisetagebuch.exe"

[Setup]
AppId={{B8E91C24-5A7F-4D3E-9C12-8F6A4B2D1E90}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} R{#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppCopyright=MIT License
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
InfoBeforeFile=NOTICE.txt
OutputDir=..\dist
OutputBaseFilename=Reisetagebuch-{#MyAppVersion}-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
UninstallDisplayIcon={app}\{#MyAppExeName}
CloseApplications=yes

[Languages]
Name: "german"; MessagesFile: "compiler:Languages\German.isl"

[Tasks]
Name: "desktopicon"; Description: "Desktop-Verknüpfung"; GroupDescription: "Zusätzlich:"; Flags: unchecked

[Files]
Source: "..\dist\Reisetagebuch\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{#MyAppName} starten"; Flags: nowait postinstall skipifsilent
