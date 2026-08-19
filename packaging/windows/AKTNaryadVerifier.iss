; Inno Setup script (user-level, no admin rights required)
; Build on Windows after PyInstaller portable build:
;   dist\AKTNaryadVerifier\...

#define MyAppName "AKTNaryadVerifier"
#define MyAppVersion "3.0"
#define MyAppPublisher "AKT Naryad Team"
#define MyAppExeName "AKTNaryadVerifier.exe"

[Setup]
AppId={{A3E20831-9532-4DB0-8F8E-4DDCA73052D6}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\..\release
OutputBaseFilename={#MyAppName}_installer_win_x64
SetupIconFile=..\..\lukoil-desk.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "..\..\dist\AKTNaryadVerifier\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\lukoil-desk.ico"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\lukoil-desk.ico"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
