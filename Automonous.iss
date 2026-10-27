; Automonous - Inno Setup installer script.
; Build:  ISCC.exe Automonous.iss
; Requires a one-dir PyInstaller build of gui_console.py (Automonous.spec)
; Playwright Chromium is NOT bundled; the app uses system Chrome/Edge.

#define MyAppName "Automonous"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "palashsuryavanshi"
#define MyAppExeName "Automonous.exe"

[Setup]
AppId={{A3F2B9C4-5D6E-4F7A-8B1C-2D3E4F5A6B7C}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Automonous
DisableProgramGroupPage=yes
PrivilegesRequired=admin
OutputDir=installer
OutputBaseFilename=Automonous-Setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
VersionInfoVersion={#MyAppVersion}
VersionInfoCopyright=Copyright (c) 2026 palashsuryavanshi
SetupIconFile=static\logo.ico

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "firewall"; Description: "Allow {#MyAppName} through Windows &Firewall (TCP port 5000)"; GroupDescription: "Permissions:"
Name: "autostart"; Description: "Start the web server automatically at &logon"; GroupDescription: "Startup:"

[Files]
Source: "dist\Automonous\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "Automonous"; ValueData: """{app}\{#MyAppExeName}"" --serve"; Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "netsh.exe"; Parameters: "advfirewall firewall add rule name=""Automonous Web App"" dir=in action=allow protocol=TCP localport=5000 profile=private"; Flags: runhidden; Tasks: firewall
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName} now"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "netsh.exe"; Parameters: "advfirewall firewall delete rule name=""Automonous Web App"""; Flags: runhidden