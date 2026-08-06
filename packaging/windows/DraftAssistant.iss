; Inno Setup script for the Draft Assistant Windows installer.
; Built by packaging/windows/build.ps1, which passes AppVersion and SourceDir.
;
; Installs per-user under %LOCALAPPDATA%\Programs by default so testers never
; see a UAC prompt. Draft state lives in %LOCALAPPDATA%\DraftAssistant (written
; by the app, not the installer) and is deliberately left behind on uninstall.

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\..\dist\pyinstaller\DraftAssistant"
#endif

#define AppName "Draft Assistant"
#define AppExeName "DraftAssistant.exe"
#define AppPublisher "Kegan Vosteen"

[Setup]
AppId={{234B944B-6E1F-4CA2-8A99-2175E0B32533}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName}
OutputDir=..\..\dist\installers
OutputBaseFilename=DraftAssistant-Setup-{#AppVersion}
SetupIconFile=..\icons\DraftAssistant.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; Per-user install: no admin rights needed, but allow an all-users install if
; the tester explicitly wants one.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(AppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Only the unpacked program files. Leagues, draft state and the player board
; live in {localappdata}\DraftAssistant and survive an uninstall/reinstall.
Type: filesandordirs; Name: "{app}\_internal"
