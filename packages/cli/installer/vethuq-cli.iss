; Inno Setup script for the VethuQ command line (Windows).
; Wraps the PyInstaller-built build\cli\vethuq\ folder into VethuQ-CLI-Setup.exe:
;
;   vethuq.exe   the command
;   lib\         the Python runtime and every dependency (Paddle, rich, SQLAlchemy, ...)
;   add-ons\     the default add-ons, one folder each (pdf\, like\, ...)
;
; Only the command line: no desktop app, no interactive shell, no background service. The OCR
; models are not part of the installer; Paddle downloads them the first time OCR runs.
;
; Install scope: Setup starts unelevated (PrivilegesRequired=lowest) and, because of
; PrivilegesRequiredOverridesAllowed=dialog, Inno's first screen asks "Install for all users" or
; "Install for me only" and elevates itself when all users is chosen. {autopf}, the uninstall entry
; and the PATH change (HKLM vs HKCU) follow the chosen scope. /ALLUSERS and /CURRENTUSER skip the
; question; /TASKS="addtopath" or /MERGETASKS="!addtopath" decide the PATH change when silent.
; Built by scripts/release/release.py --cli and .github/workflows/release-cli.yml.

#define MyAppName "VethuQ"
#ifndef MyAppVersion
  #define MyAppVersion "0.1.0"
#endif
#define MyAppExeName "vethuq.exe"
; Numeric a.b.c.d for the file's version info (MyAppVersion may carry a pre-release suffix).
#ifndef MyAppNumericVersion
  #define MyAppNumericVersion "0.1.0.0"
#endif

[Setup]
; A GUID of its own: the CLI installs and uninstalls independently of any other VethuQ installer.
AppId={{0C3F6B1E-7D52-4B8A-9E1D-5A4F2C8E7B30}
AppName={#MyAppName} CLI
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} CLI v{#MyAppVersion}
AppPublisher=coldsofttech
AppPublisherURL=https://github.com/coldsofttech/VethuQ
VersionInfoVersion={#MyAppNumericVersion}
LicenseFile=LICENSE.rtf
; The VethuQ icon: the installer/uninstaller exe, Apps & Features, and the wizard's side and header images.
SetupIconFile=vethuq.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
WizardImageFile=wizard_large.bmp
WizardSmallImageFile=wizard_small.bmp
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog commandline
DefaultDirName={autopf}\{#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\..\..\dist
OutputBaseFilename=VethuQ-CLI-Setup
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SolidCompression=yes
LZMAUseSeparateProcess=yes
#ifdef NoCompression
; Local `release.py --cli --dev` builds: no compression, so the build is quick.
Compression=none
#else
; The folder holds plain library files, so a strong solid LZMA2 pass shrinks it a lot.
Compression=lzma2/ultra64
#ifndef CompressThreads
  #define CompressThreads 1
#endif
LZMANumBlockThreads={#CompressThreads}
#endif

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "vethuq.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\..\build\cli\vethuq\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\..\build\cli\vethuq\lib\*"; DestDir: "{app}\lib"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\..\build\cli\vethuq\add-ons\*"; DestDir: "{app}\add-ons"; Flags: ignoreversion recursesubdirs createallsubdirs

[UninstallDelete]
; The interactive shell (VethuQ-Interactive-CLI-Setup.exe) lives in this folder and relies on lib\.
Type: files; Name: "{app}\vethuqic.exe"
Type: files; Name: "{app}\unins001.*"

[Tasks]
Name: "addtopath"; Description: "Add VethuQ to PATH (lets you run ""vethuq"" from any terminal)"; GroupDescription: "Command line:"; Flags: checkedonce

[Code]
const
  SystemEnvironmentKey = 'SYSTEM\CurrentControlSet\Control\Session Manager\Environment';
  UserEnvironmentKey = 'Environment';

{ PATH lives in HKLM for an all-users install, HKCU for a per-user one.
  IsAdminInstallMode is also valid while uninstalling (it reflects the scope
  the app was installed in). }
function EnvRootKey: Integer;
begin
  if IsAdminInstallMode then
    Result := HKEY_LOCAL_MACHINE
  else
    Result := HKEY_CURRENT_USER;
end;

function EnvironmentKey: string;
begin
  if IsAdminInstallMode then
    Result := SystemEnvironmentKey
  else
    Result := UserEnvironmentKey;
end;

function SendMessageTimeoutA(
  hWnd: Longint; Msg: Longint; wParam: Longint; lParam: AnsiString;
  fuFlags: Longint; uTimeout: Longint; var lpdwResult: Longint
): Longint;
  external 'SendMessageTimeoutA@user32.dll stdcall';

procedure RefreshEnvironment;
var
  MsgResult: Longint;
begin
  SendMessageTimeoutA(
    $FFFF { HWND_BROADCAST }, $1A { WM_SETTINGCHANGE }, 0, 'Environment',
    2 { SMTO_ABORTIFHUNG }, 2000, MsgResult
  );
end;

function EnvPathContains(const Paths, Path: string): Boolean;
begin
  Result := Pos(';' + Uppercase(Path) + ';', ';' + Uppercase(Paths) + ';') > 0;
end;

procedure EnvAddPath(const Path: string);
var
  Paths: string;
begin
  if not RegQueryStringValue(EnvRootKey, EnvironmentKey, 'Path', Paths) then
    Paths := '';

  if EnvPathContains(Paths, Path) then
    exit;

  if (Paths <> '') and (Paths[Length(Paths)] <> ';') then
    Paths := Paths + ';';
  Paths := Paths + Path;

  if RegWriteExpandStringValue(EnvRootKey, EnvironmentKey, 'Path', Paths) then
    RefreshEnvironment;
end;

procedure EnvRemovePath(const Path: string);
var
  Paths: string;
  P: Integer;
begin
  if not RegQueryStringValue(EnvRootKey, EnvironmentKey, 'Path', Paths) then
    exit;

  P := Pos(';' + Uppercase(Path) + ';', ';' + Uppercase(Paths) + ';');
  if P = 0 then
    exit;

  Delete(Paths, P - 1, Length(Path) + 1);

  if RegWriteExpandStringValue(EnvRootKey, EnvironmentKey, 'Path', Paths) then
    RefreshEnvironment;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and WizardIsTaskSelected('addtopath') then
    EnvAddPath(ExpandConstant('{app}'));
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
    EnvRemovePath(ExpandConstant('{app}'));
end;
