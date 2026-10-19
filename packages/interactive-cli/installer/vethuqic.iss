; Inno Setup script for the VethuQ interactive shell (Windows).
; Adds vethuqic.exe to an existing VethuQ command-line install: the same folder, reusing its lib\ and
; add-ons\. It needs the VethuQ CLI installer (packages/cli/installer/vethuq-cli.iss) run first, from
; the same build: Setup refuses to run when the CLI is missing, or when the CLI's lib\ was built
; from different dependencies (lib\runtime-id.txt differs from the one this installer was built with).
;
; Only the interactive shell: no desktop app, no second copy of the command line. The CLI installer's
; uninstaller removes vethuqic.exe along with the rest of the folder.
; Built by scripts/release/release.py --interactive-cli and .github/workflows/release-interactive-cli.yml.

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
#define MyAppExeName "vethuqic.exe"
#define ProgramName "interactive shell"
; The CLI installer's AppId (without the braces' doubling): where Windows records its install folder.
#define CliAppId "0C3F6B1E-7D52-4B8A-9E1D-5A4F2C8E7B30"

[Setup]
AppId={{6D2A9C47-3B1E-4F85-A7C0-8E5D1B3F9A62}
AppName={#MyAppName} Interactive CLI
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} Interactive CLI v{#MyAppVersion}
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
OutputBaseFilename=VethuQ-Interactive-CLI-Setup
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

[Files]
Source: "..\..\..\build\cli\vethuq\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
; A console program: Windows opens it in a terminal window. The Start menu folder (Start > Programs >
; VethuQ) is shared with the other installers; each removes only its own shortcuts.
Name: "{autoprograms}\VethuQ\VethuQ Interactive CLI"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\vethuq.ico"; Comment: "Menus over the VethuQ commands"
Name: "{autoprograms}\VethuQ\Uninstall VethuQ Interactive CLI"; Filename: "{uninstallexe}"; IconFilename: "{app}\vethuq.ico"; Comment: "Remove the VethuQ interactive CLI"
Name: "{autodesktop}\VethuQ Interactive CLI"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\vethuq.ico"; Comment: "Menus over the VethuQ commands"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "addtopath"; Description: "Add VethuQ to PATH (lets you run ""vethuqic"" from any terminal)"; GroupDescription: "Command line:"; Flags: checkedonce

[Code]
#include "..\..\..\installer\shared\into_cli_folder.iss"

function InitializeSetup: Boolean;
begin
  Result := CliFolderReady;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and WizardIsTaskSelected('addtopath') then
    EnvAddPath(ExpandConstant('{app}'));
end;
