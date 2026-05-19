#define MyAppName "Codex Proxy Control"
#define MyAppVersion "0.4.3"
#ifndef SourceDir
#define SourceDir "dist\windows"
#endif

[Setup]
AppId={{3E03DE59-0765-4F23-A285-9D9FB7DD06AF}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=fank1ng
DefaultDirName={localappdata}\Programs\Codex Proxy Control
DefaultGroupName=Codex Proxy Control
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
Compression=lzma2
SolidCompression=yes
OutputDir=..\dist
OutputBaseFilename=CodexProxyControlSetup-{#MyAppVersion}
UninstallDisplayIcon={app}\Codex Proxy Control.exe

[Files]
Source: "{#SourceDir}\Codex Proxy Control.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceDir}\CodexProxyService.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceDir}\runtime\*"; DestDir: "{app}\runtime"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Codex Proxy Control"; Filename: "{app}\Codex Proxy Control.exe"
Name: "{autodesktop}\Codex Proxy Control"; Filename: "{app}\Codex Proxy Control.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Run]
Filename: "{app}\Codex Proxy Control.exe"; Description: "Launch Codex Proxy Control"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{app}\CodexProxyService.exe"; Parameters: "--uninstall"; Flags: runhidden waituntilterminated
