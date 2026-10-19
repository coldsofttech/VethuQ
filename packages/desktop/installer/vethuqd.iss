; Inno Setup script for the VethuQ desktop application (Windows).
; Adds vethuqd.exe to an existing VethuQ command-line install: the same folder, reusing its lib\ and
; add-ons\. It needs the VethuQ CLI installer (packages/cli/installer/vethuq-cli.iss) run first, from
; the same build: Setup refuses to run when the CLI is missing, or when the CLI's lib\ was built
; from different dependencies (lib\runtime-id.txt differs from the one this installer was built with).
;
; Only the desktop application (a window over the local API; it needs the WebView2 runtime that
; Windows 11 includes): no second copy of the command line. The CLI installer's
; uninstaller removes vethuqd.exe along with the rest of the folder.
; Built by scripts/release/release.py --desktop and .github/workflows/release-desktop.yml.

#define MyAppName "VethuQ"
#ifndef MyAppVersion
  #define MyAppVersion "0.1.0"
#endif
#ifndef MyAppNumericVersion
  #define MyAppNumericVersion "0.1.0.0"
#endif
; The id of the build's lib\ (a hash), passed in by release.py.
#ifndef RuntimeId
  #define RuntimeId "dev"
#endif
#define MyAppExeName "vethuqd.exe"
#define ProgramName "desktop application"
; The CLI installer's AppId (without the braces' doubling): where Windows records its install folder.
#define CliAppId "0C3F6B1E-7D52-4B8A-9E1D-5A4F2C8E7B30"

[Setup]
AppId={{E3A8C15F-6B72-4D09-9C4E-1F7B2A5D8E36}
AppName={#MyAppName} Desktop
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} Desktop v{#MyAppVersion}
AppPublisher=coldsofttech
AppPublisherURL=https://github.com/coldsofttech/VethuQ
VersionInfoVersion={#MyAppNumericVersion}
LicenseFile=..\..\..\installer\shared\LICENSE.rtf
SetupIconFile=..\..\..\installer\shared\vethuq.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
WizardImageFile=..\..\..\installer\shared\wizard_large.bmp
WizardSmallImageFile=..\..\..\installer\shared\wizard_small.bmp
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog commandline
; The CLI's folder, found in InitializeSetup.
DefaultDirName={code:CliDir}
UsePreviousAppDir=no
DisableDirPage=yes
DisableProgramGroupPage=yes
OutputDir=..\..\..\dist
OutputBaseFilename=VethuQ-Desktop-Setup
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SolidCompression=yes
#ifdef NoCompression
Compression=none
#else
Compression=lzma2/ultra64
#endif

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Dirs]
; The device folder: licences and the credit ledger, shared by every account on this computer and by
; the background service (see vethuq._paths.device). An all-users install creates it here, open to
; the Users group; a per-user install can't, so VethuQ makes it on first use if the account may, and
; otherwise keeps those in the account's own data folder. Never removed by an uninstall, so
; reinstalling does not hand out a fresh allowance.
Name: "{commonappdata}\VethuQ"; Permissions: users-modify; Flags: uninsneveruninstall; Check: IsAdminInstallMode

[Files]
Source: "..\..\..\build\cli\vethuq\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
; The Start menu folder (Start > Programs > VethuQ) is shared with the other installers; each removes only its own shortcuts.
Name: "{autoprograms}\VethuQ\VethuQ"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\vethuq.ico"; Comment: "Search your documents"
Name: "{autodesktop}\VethuQ"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\vethuq.ico"; Tasks: desktopicon
Name: "{autoprograms}\VethuQ\Uninstall VethuQ"; Filename: "{uninstallexe}"; IconFilename: "{app}\vethuq.ico"; Comment: "Remove the VethuQ desktop application"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Start VethuQ"; Flags: nowait postinstall skipifsilent

[Code]
#include "..\..\..\installer\shared\into_cli_folder.iss"

function InitializeSetup: Boolean;
begin
  Result := CliFolderReady;
end;
