; Inno Setup script for the VethuQ worker (Windows).
; Adds vethuqw.exe to an existing VethuQ command-line install: the same folder as vethuq.exe, vethuqic.exe
; and vethuqbs.exe, reusing its lib\ and add-ons\. Like theirs it needs the CLI installer run first, from
; the same build (see installer\shared\into_cli_folder.iss).
;
; Only the worker: `vethuqw run --job-id ID --payload DIR --out DIR` reads a job's pages (the key is in
; VETHUQ_MASTER_KEY) for a GitHub runner; it reads with whatever add-ons are in add-ons\. The OCR models
; are not part of the installer: `vethuqw bake-models --models DIR` downloads them, and VETHUQ_MODELS
; points the worker at them. It is not a service and has nothing to clean up when uninstalled beyond its
; exe, which the command line's uninstaller removes too.
; Built by scripts/release/release.py --worker and .github/workflows/release-worker.yml.

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
#define MyAppExeName "vethuqw.exe"
#define ProgramName "worker"
; The CLI installer's AppId: where Windows records its install folder.
#define CliAppId "0C3F6B1E-7D52-4B8A-9E1D-5A4F2C8E7B30"

[Setup]
AppId={{E3A5C718-94D2-4B6F-A0E7-1D8C5B3F2A96}
AppName={#MyAppName} Worker
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} Worker v{#MyAppVersion}
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
OutputBaseFilename=VethuQ-Worker-Setup
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
; The Start menu folder (Start > Programs > VethuQ) is shared with the other installers; each removes only its own shortcuts.
Name: "{autoprograms}\VethuQ\Uninstall VethuQ Worker"; Filename: "{uninstallexe}"; IconFilename: "{app}\vethuq.ico"; Comment: "Remove the VethuQ worker"

[Code]
#include "..\..\..\installer\shared\into_cli_folder.iss"

function InitializeSetup: Boolean;
begin
  Result := CliFolderReady;
end;
